"""FirstWell Essentials staff-only, two-stage Supabase XLSX uploader.
Register with register_upload_api(app). Existing Flask staff auth + CSRF covers routes.
Original source rows are never replaced; conflicts require explicit administrative review.
"""
import datetime as dt
import hashlib
import uuid as uuidlib
import json
import os
import re
import secrets
import tempfile
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from flask import Blueprint, current_app, g, jsonify, request
from werkzeug.utils import secure_filename
from process_month import open_workbook, read_inventory, read_movement, read_shopee_perf, read_shopee_price

bp = Blueprint('supabase_uploader', __name__, url_prefix='/api/supabase-upload')
ROOT = Path(__file__).resolve().parent.parent
KINDS = {'inventory': 'inventory', 'movement': 'movement', 'my_perf': 'myPerf',
         'sg_perf': 'sgPerf', 'my_price': 'myPrice', 'sg_price': 'sgPrice'}
MKT = {'my_perf': 'MY', 'sg_perf': 'SG', 'my_price': 'MY', 'sg_price': 'SG'}
SESSION_TTL = dt.timedelta(minutes=45)


def d(value):
    if value is None: return None
    return str(Decimal(str(value)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))


def ident(value):
    if value is None: return ''
    s = str(value).strip()
    return s[:-2] if s.endswith('.0') and s[:-2].isdigit() else s


def iso_date(raw):
    if isinstance(raw, (dt.datetime, dt.date)): return raw.date().isoformat() if isinstance(raw, dt.datetime) else raw.isoformat()
    raw = str(raw or '').strip().split(' ')[0]
    for fmt in ('%d/%m/%Y', '%Y-%m-%d'):
        try: return dt.datetime.strptime(raw, fmt).date().isoformat()
        except ValueError: pass
    return None


def month_end(month):
    y, m = map(int, month.split('-'))
    return (dt.date(y + (m == 12), m % 12 + 1, 1) - dt.timedelta(days=1)).isoformat()


def fail(message, code=400):
    return jsonify(error=message), code


def client():
    from supabase import create_client
    url, key = os.getenv('SUPABASE_URL'), os.getenv('SUPABASE_SERVICE_ROLE_KEY')
    if not url or not key: raise ValueError('Supabase server credentials are missing from .env')
    return create_client(url, key)


def fetch_all(db, table, columns, filters=None, sort='id'):
    rows, start = [], 0
    while True:
        q = db.table(table).select(columns).order(sort)
        for k, v in (filters or {}).items(): q = q.eq(k, v)
        batch = q.range(start, start + 499).execute().data or []
        rows.extend(batch)
        if len(batch) < 500: return rows
        start += 500


STAGE_TABLE = 'supabase_upload_previews'


def stage_put(db, token, staff_id, kind, month, snapshot, name, fingerprint, prepared):
    """Keep the preview in Supabase (not a local file), so it also works on Vercel where the disk is read-only
    and the preview and accept requests may run on different instances."""
    cutoff = (dt.datetime.now(dt.timezone.utc) - SESSION_TTL).isoformat()
    db.table(STAGE_TABLE).delete().lt('created_at', cutoff).execute()
    db.table(STAGE_TABLE).insert(dict(token=token, staff_id=staff_id, kind=kind, month=month, snapshot=snapshot,
                                      name=name, fingerprint=fingerprint, prepared_json=prepared)).execute()


def stage_get(db, token, staff_id):
    rows = db.table(STAGE_TABLE).select('*').eq('token', token).eq('staff_id', staff_id).limit(1).execute().data or []
    return rows[0] if rows else None


def stage_delete(db, token):
    db.table(STAGE_TABLE).delete().eq('token', token).execute()


def detect_kind(path, filename, chosen):
    if chosen in KINDS:
        if chosen.endswith('_price'):
            low = filename.casefold()
            if re.search(r'(^|[^a-z])sg([^a-z]|$)|singapore',low) and chosen=='my_price':
                raise ValueError('Singapore price filename selected as MY. Choose SG or upload the correct MY file.')
            if re.search(r'(^|[^a-z])my([^a-z]|$)|malaysia',low) and chosen=='sg_price':
                raise ValueError('Malaysia price filename selected as SG. Choose MY or upload the correct SG file.')
        return chosen
    wb = open_workbook(str(path))
    if {'Summary', 'Multiple Expiry'} <= set(wb.sheetnames): return 'inventory'
    if 'Top Performing Products' in wb.sheetnames:
        ws = wb['Top Performing Products']
        headers = {str(c.value or '').strip() for c in ws[1]}
        if 'Sales (Confirmed Order) (MYR)' in headers: return 'my_perf'
        if 'Sales (Paid Order) (SGD)' in headers: return 'sg_perf'
    ws = wb.worksheets[0]
    heads = [[str(c.value or '').strip() for c in row] for row in ws.iter_rows(min_row=1, max_row=12)]
    if any('Sold' in row and 'Closing Balance' in row for row in heads): return 'movement'
    if any({'Product ID', 'Variation ID', 'Price'} <= set(row) for row in heads):
        # Better to refuse than silently send a price report to the wrong market.
        lower = filename.lower()
        if re.search(r'(^|[^a-z])my([^a-z]|$)|malaysia', lower): return 'my_price'
        if re.search(r'(^|[^a-z])sg([^a-z]|$)|singapore', lower): return 'sg_price'
        raise ValueError('Price sheet detected. Select Shopee MY or Shopee SG Prices explicitly.')
    raise ValueError('Unknown workbook. Select a supported original Avixo or Shopee XLSX report.')


def product_lookup(db):
    all_products = fetch_all(db, 'products', 'id,avixo_id,name', sort='avixo_id')
    ids = {ident(p['avixo_id']): p['id'] for p in all_products}
    names = defaultdict(set)
    for p in all_products: names[str(p['name'] or '').strip().casefold()].add(p['id'])
    return ids, names


def owners_lookup(db, market):
    links = fetch_all(db, 'product_channel_links',
                      'id,marketplace,shopee_item_id,shopee_variation_id,product_id,observed_on',
                      {'marketplace': market})
    if not links: return {}, {}
    newest = max(str(x['observed_on']) for x in links)
    owners = defaultdict(set)
    parents = defaultdict(list)
    for x in links:
        if str(x['observed_on']) != newest: continue
        item, var = ident(x['shopee_item_id']), ident(x['shopee_variation_id']) or '0'
        owners[(item,var)].add(x['product_id'])
        parents[item].append((var,x['product_id']))
    exact = {key:next(iter(vals)) for key,vals in owners.items() if len(vals)==1}
    only_parent = {}
    for item, variants in parents.items():
        if {v for v,p in variants} == {'0'} and len({p for v,p in variants})==1:
            only_parent[item] = variants[0][1]
    return exact, only_parent


def prepare(path, kind, month, snapshot, db, clinic_price_mode="historical"):
    report_date = month+'-01'
    tables = {}
    warnings = []
    meta = {}
    if kind in ('my_perf', 'sg_perf'):
        market = MKT[kind]
        currency = 'MYR' if market == 'MY' else 'SGD'
        units_col = 'Units (Confirmed Order)' if market == 'MY' else 'Units (Paid Order)'
        money_col = 'Sales (Confirmed Order) (MYR)' if market == 'MY' else 'Sales (Paid Order) (SGD)'
        parents, variations = read_shopee_perf(str(path), units_col, money_col)
        exact, only_parent = owners_lookup(db, market)
        grouped = defaultdict(list)
        for (item,var), info in variations.items(): grouped[ident(item)].append((ident(var),info))
        # Validate entire variation breakdown before storing any sales.
        for item, parts in grouped.items():
            p = parents.get(item)
            if p is None: raise ValueError(f'Variation for item {item} has no parent row.')
            vu = sum(Decimal(str(x.get('units') or 0)) for _,x in parts)
            vr = sum(Decimal(str(x.get('sales') or 0)) for _,x in parts)
            if abs(vu-Decimal(str(p.get('units') or 0))) > Decimal('.01') or abs(vr-Decimal(str(p.get('sales') or 0))) > Decimal('.05'):
                raise ValueError(f'Variation sales do not reconcile for Shopee item {item}.')
        p_rows=[]; v_rows=[]
        for item, val in parents.items():
            item = ident(item)
            p_rows.append(dict(report_month=report_date,marketplace=market,shopee_item_id=item,
                name_in_report=str(val.get('name') or ''),units_sold=d(val.get('units') or 0),sales_amount=d(val.get('sales') or 0),
                currency=currency,product_id=only_parent.get(item), mapping_status='matched' if item in only_parent else 'unmapped'))
        fingerprint=hashlib.sha256(path.read_bytes()).hexdigest()
        for (item,var), val in variations.items():
            item,var=ident(item),ident(var)
            if not item or not var or var=='-':raise ValueError('Invalid Shopee variation identifier')
            uuid=exact.get((item,var))
            v_rows.append(dict(report_month=report_date,marketplace=market,shopee_item_id=item,shopee_variation_id=var,
                units_sold=d(val.get('units') or 0),sales_amount=d(val.get('sales') or 0),currency=currency,
                product_id=uuid,mapping_basis='latest observed Avixo links; historical association provisional' if uuid else None,
                source_filename=path.name,source_sha256=fingerprint))
        if not p_rows: raise ValueError('No Shopee parent records detected')
        tables['shopee_sales_monthly'] = p_rows
        tables['shopee_variation_sales_monthly'] = v_rows
        meta['units']=d(sum(Decimal(x['units_sold']) for x in p_rows))
        meta['revenue']=d(sum(Decimal(x['sales_amount']) for x in p_rows))
        meta['currency']=currency
        meta['variation_records']=len(v_rows)
        meta['unmapped_parent_records']=sum(x['product_id'] is None for x in p_rows)
        meta['unmapped_variations']=sum(x['product_id'] is None for x in v_rows)
        warnings.append('Parent and variation sales are stored separately. Never add both in reporting.')
        warnings.append('Historical Avixo links are inferred from the latest available mapping snapshot.')
        # Filename date ranges when present must agree with selected reporting month.
        match=re.search(r'(20\d{6})[_-](20\d{6})',path.name)
        if match:
            try: mm=dt.datetime.strptime(match.group(1),'%Y%m%d').strftime('%Y-%m')
            except ValueError: raise ValueError('Invalid date in performance filename')
            if mm!=month: raise ValueError('Selected month disagrees with the sales filename')
        else: warnings.append('File name does not prove its reporting month. Verify the selected month manually.')
    elif kind in ('my_price','sg_price'):
        market=MKT[kind]
        if not snapshot: raise ValueError('Select the price snapshot date (when the report was exported).')
        currency='MYR' if market=='MY' else 'SGD'
        prices,_=read_shopee_price(str(path))
        p_rows=[]
        for (item,var),price in prices.items():
            item,var=ident(item),ident(var) or '0'
            if not item.isdigit() or not var.isdigit(): raise ValueError('Invalid Shopee listing ID')
            if price is None or Decimal(str(price))<=0:raise ValueError(f'Missing or non-positive price: {item}/{var}')
            p_rows.append(dict(marketplace=market,shopee_item_id=item,shopee_variation_id=var,
                               snapshot_date=snapshot,listed_price=d(price),currency=currency))
        if not p_rows:raise ValueError('No valid listing prices detected')
        tables['listing_price_snapshots']=p_rows
        meta['currency']=currency
        warnings.append('Listing price is a dated snapshot, not realized customer transaction price.')
    elif kind=='inventory':
        products,batches,embedded=read_inventory(str(path))
        embedded_date=iso_date(embedded)
        if embedded_date and snapshot and snapshot!=embedded_date:
            raise ValueError(f'Inventory date in workbook is {embedded_date}; selected date disagrees.')
        snapshot=snapshot or embedded_date
        if not snapshot: raise ValueError('Enter inventory snapshot date')
        # First inventory report for a brand-new database: any date in the month is accepted and
        # products are created from the report, because there is nothing earlier to protect.
        first_import=not (db.table('inventory_snapshots').select('product_id').limit(1).execute().data or [])
        last=dt.date.fromisoformat(month_end(month))
        if first_import:
            first_day=dt.date.fromisoformat(month+'-01')
            if not (first_day.isoformat()<=snapshot<=(last+dt.timedelta(days=1)).isoformat()):
                raise ValueError('Inventory snapshot date must be inside the selected month.')
            if snapshot not in (last.isoformat(),(last+dt.timedelta(days=1)).isoformat()):
                warnings.append('First inventory report: mid-month date accepted. Monthly views still use the month-end report, so upload that too when it is ready.')
        elif snapshot not in (last.isoformat(),(last+dt.timedelta(days=1)).isoformat()):
            raise ValueError('Inventory snapshot should be month-end or the following day.')
        ids,_=product_lookup(db)
        s_rows=[];b_rows=[];unknown=[];new_products=[]
        for p in products:
            key=ident(p.get('id'))
            if not key:continue
            if key not in ids and first_import:
                ids[key]=str(uuidlib.uuid4())
                new_products.append(dict(id=ids[key],avixo_id=key,name=str(p.get('name') or key).strip(),
                    category=str(p.get('cat') or 'Uncategorised').strip() or 'Uncategorised',stock_unit=str(p.get('unit') or '') or None))
            if key not in ids:
                unknown.append(f'{key}: {p.get("name")}')
                continue
            pid=ids[key]; bs=batches.get(p['name'],[])
            s_rows.append(dict(product_id=pid,snapshot_date=snapshot,quantity=d(sum(Decimal(str(b.get('qty') or 0)) for b in bs)),
              latest_cost_rm=d(p.get('latest_cost')),clinic_list_price_rm=d(p.get('price')),
              stock_value_rm=d(sum(Decimal(str(b.get('value_cost') or 0)) for b in bs)),
              summary_balance=d(p.get('summary_balance')),stock_unit=str(p.get('unit') or '')))
            for number,b in enumerate(bs,1):
                b_rows.append(dict(product_id=pid,snapshot_date=snapshot,batch_number=number,
                   expiry_date=b['expiry'].isoformat() if b['expiry'] else None,quantity=d(b.get('qty') or 0),
                   stock_cost_value_rm=d(b.get('value_cost') or 0),stock_retail_value_rm=d(b.get('value_retail') or 0)))
        if unknown: raise ValueError('Unknown Avixo IDs; import/update products first: '+', '.join(unknown[:5]))
        if not s_rows: raise ValueError('No inventory records with known Avixo IDs')
        if new_products:
            tables['products']=new_products
            warnings.append(f'First inventory report: {len(new_products)} products will be created from this file.')
        tables['inventory_snapshots']=s_rows;tables['inventory_batches']=b_rows
        meta.update(snapshot_date=snapshot,stock_units=d(sum(Decimal(x['quantity']) for x in s_rows)),
                    stock_value_rm=d(sum(Decimal(x['stock_value_rm']) for x in s_rows)),expiry_batches=len(b_rows))
        warnings.append('Inventory updates existing Avixo products only. New product identities require separate validation.')
    elif kind=='movement':
        move, period=read_movement(str(path))
        # The period metadata must match selected month.
        m=re.search(r'From:\s*(\d{2}/\d{2}/\d{4})\s*-\s*To:\s*(\d{2}/\d{2}/\d{4})',str(period))
        if not m: raise ValueError('Movement report has no readable From/To dates; upload original workbook.')
        start,end=iso_date(m.group(1)),iso_date(m.group(2))
        if start!=month+'-01' or not end.startswith(month):raise ValueError('Movement report period does not match reporting month')
        if snapshot and snapshot!=end: raise ValueError('Selected movement end date differs from workbook end date')
        _,names=product_lookup(db)
        # Clinic selling prices come ONLY from the Avixo INVENTORY report's Price
        # column, stored as clinic_list_price_rm. Movement supplies Sold only.
        prices=fetch_all(db,'inventory_snapshots','product_id,snapshot_date,clinic_list_price_rm', sort='product_id')
        relevant={}
        # Historical mode accepts snapshots no later than the next month's first day.
        # Latest mode is opt-in and uses one consistent latest snapshot date,
        # not arbitrary different dates per product.
        cutoff=(dt.date.fromisoformat(month_end(month))+dt.timedelta(days=1)).isoformat()
        if clinic_price_mode=='latest':
            eligible_dates=[str(p['snapshot_date']) for p in prices if p.get('clinic_list_price_rm') is not None]
            chosen_date=max(eligible_dates) if eligible_dates else None
        else:
            chosen_date=None
        for p in prices:
            when=str(p['snapshot_date'])
            if clinic_price_mode=='latest':
                eligible=bool(chosen_date and when==chosen_date)
            else:
                eligible=when<=cutoff
            if eligible and (p['product_id'] not in relevant or str(relevant[p['product_id']]['snapshot_date'])<when):
                relevant[p['product_id']]=p
        rows=[];unmatched=[]
        for name,v in move.items():
            sold=Decimal(str(v.get('sold') or 0))
            if sold==0:continue
            owners=names.get(name.strip().casefold(),set())
            if len(owners)!=1:
                unmatched.append(name)
                continue
            pid=next(iter(owners));price=relevant.get(pid,{})
            pv=price.get('clinic_list_price_rm')
            rows.append(dict(report_month=report_date,avixo_name_in_report=name,product_id=pid,
               units_sold=d(sold),estimated_revenue_rm=d(sold*Decimal(str(pv))) if pv is not None else None,
               price_snapshot_date=price.get('snapshot_date')))
        if unmatched:raise ValueError('Clinic names unmatched or ambiguous: '+', '.join(unmatched[:6]))
        if not rows:raise ValueError('No nonzero clinic sales found')
        tables['clinic_movement_monthly']=rows
        meta['units']=d(sum(Decimal(x['units_sold']) for x in rows))
        meta['missing_prices']=sum(x['estimated_revenue_rm'] is None for x in rows)
        meta['priced_products']=len(rows)-meta['missing_prices']
        meta['revenue_status']='Unavailable' if meta['priced_products']==0 else ('Incomplete estimate' if meta['missing_prices'] else 'Complete estimate')
        meta['revenue_price_source']='Avixo Inventory Report → Price (not Cost Price)'
        meta['price_mode']=clinic_price_mode
        meta['price_snapshot_date']=chosen_date if clinic_price_mode=='latest' else max(
            (str(r['price_snapshot_date']) for r in rows if r['price_snapshot_date']), default=None)
        # A total of zero with no priced products is NOT zero sales revenue.
        meta['estimated_revenue_rm']=(
            d(sum(Decimal(x['estimated_revenue_rm']) for x in rows if x['estimated_revenue_rm'] is not None))
            if meta['priced_products'] else None)
        if meta['missing_prices']:
            warnings.append(f"{meta['missing_prices']} of {len(rows)} products lack usable Clinic selling prices. Revenue is incomplete and must not be treated as full-month revenue.")
        if clinic_price_mode=='latest':
            warnings.append('STAFF-SELECTED ESTIMATE: movement valued using the latest inventory selling prices on '
                            +str(chosen_date or 'no available date')+'. These are NOT historical transaction prices.')
        else:
            warnings.append('Historical-price mode: later inventory prices are excluded. Importing units without revenue is allowed.')
        warnings.append('Clinic revenue is estimated from stock snapshot prices; sales are not transaction-level.')
        warnings.append('Movement periods may be partial-month; only the provided period is represented.')
    return tables, meta, warnings, snapshot


KEYS = {
 'shopee_sales_monthly': ('report_month','marketplace','shopee_item_id'),
 'shopee_variation_sales_monthly': ('report_month','marketplace','shopee_item_id','shopee_variation_id'),
 'listing_price_snapshots': ('marketplace','shopee_item_id','shopee_variation_id','snapshot_date'),
 'inventory_snapshots': ('product_id','snapshot_date'),
 'inventory_batches': ('product_id','snapshot_date','batch_number'),
 'clinic_movement_monthly': ('report_month','avixo_name_in_report'),
 'products': ('avixo_id',),
}
COMPARE = {
 'shopee_sales_monthly': ('report_month','marketplace','shopee_item_id','units_sold','sales_amount','currency'),
 'shopee_variation_sales_monthly': ('report_month','marketplace','shopee_item_id','shopee_variation_id','units_sold','sales_amount','currency'),
 'listing_price_snapshots': ('marketplace','shopee_item_id','shopee_variation_id','snapshot_date','listed_price','currency'),
 'inventory_snapshots': ('product_id','snapshot_date','quantity','latest_cost_rm','clinic_list_price_rm','stock_value_rm','summary_balance'),
 'inventory_batches': ('product_id','snapshot_date','batch_number','expiry_date','quantity','stock_cost_value_rm','stock_retail_value_rm'),
 'clinic_movement_monthly': ('report_month','avixo_name_in_report','units_sold','estimated_revenue_rm','price_snapshot_date'),
 'products': ('avixo_id','name'),
}
SORT = {'products':'avixo_id','inventory_snapshots':'product_id','inventory_batches':'product_id','listing_price_snapshots':'shopee_item_id','clinic_movement_monthly':'id'}


def normval(v):
    if v is None:return ''
    if isinstance(v,(int,float,Decimal)) or (isinstance(v,str) and re.fullmatch(r'-?\d+(\.\d+)?',v)):
        try:return ('%.5f' % Decimal(str(v))).rstrip('0').rstrip('.')
        except Exception:pass
    return str(v).strip()


def status_for(db,tables, allow_resume=False):
    summary={}; conflicts=[]; scopes=[]
    for table,rows in tables.items():
        if not rows:continue
        keys=[tuple(ident(x.get(k)) for k in KEYS[table]) for x in rows]
        if len(keys)!=len(set(keys)):
            conflicts.append(f'{table}: duplicate source identities detected')
        scope={}
        key0=rows[0]
        if table in ('shopee_sales_monthly','shopee_variation_sales_monthly'):
            scope={'report_month':key0['report_month'],'marketplace':key0['marketplace']}
        elif table=='listing_price_snapshots':scope={'snapshot_date':key0['snapshot_date'],'marketplace':key0['marketplace']}
        elif table in ('inventory_snapshots','inventory_batches'):scope={'snapshot_date':key0['snapshot_date']}
        elif table=='products':scope={}
        else:scope={'report_month':key0['report_month']}
        existing=fetch_all(db,table,','.join(set(KEYS[table]+COMPARE[table])),scope,SORT.get(table,'id'))
        old={tuple(ident(x.get(k)) for k in KEYS[table]):x for x in existing}
        new={tuple(ident(x.get(k)) for k in KEYS[table]):x for x in rows}
        newkeys=set(new)-set(old); shared=set(new)&set(old); missing=set(old)-set(new)
        changed=[k for k in shared if any(normval(new[k].get(c))!=normval(old[k].get(c)) for c in COMPARE[table])]
        summary[table]={'source_rows':len(rows),'existing_rows':len(old),'new':len(newkeys),'identical':len(shared)-len(changed),'changed':len(changed),'missing':len(missing)}
        # In an already populated scope, no additional records from different files are accepted.
        if table=='products':
            # Only brand-new products are proposed here; other existing products are not "missing".
            if old and not allow_resume:conflicts.append(f'products: {len(old)} already exist; upload again for a fresh preview')
            continue
        if changed or missing or (old and newkeys and not allow_resume):
            conflicts.append(f'{table}: {len(changed)} changed, {len(missing)} missing, {len(newkeys)} new against an existing scope')
    return summary,conflicts


def fingerprint_for(path,kind):
    # Upload channel has its own import provenance, distinct from old CLI importer prefixes.
    return hashlib.sha256(('firstwell-web-'+kind+':').encode()+path.read_bytes()).hexdigest()


@bp.post('/preview')
def preview():
    month=request.form.get('month','').strip()
    if not re.fullmatch(r'20\d{2}-(0[1-9]|1[0-2])',month):return fail('Choose a valid reporting month.')
    uploaded=request.files.get('file')
    if not uploaded or not uploaded.filename:return fail('Choose an XLSX file.')
    if Path(uploaded.filename).suffix.lower()!='.xlsx':return fail('Supabase import currently supports original XLSX reports only. CSV is not supported yet.')
    file_name=secure_filename(uploaded.filename)[:180]
    snapshot=request.form.get('snapshot_date','').strip() or None
    if snapshot:
        try:dt.date.fromisoformat(snapshot)
        except ValueError:return fail('Invalid snapshot date')
    clinic_price_mode=request.form.get('clinic_price_mode','historical')
    if clinic_price_mode not in ('historical','latest'):return fail('Unsupported Clinic pricing mode')
    chosen=request.form.get('kind','auto')
    if chosen!='auto' and chosen not in KINDS:return fail('Unsupported report type')
    with tempfile.TemporaryDirectory(prefix='firstwell_preview_',ignore_cleanup_errors=True) as folder:
        path=Path(folder)/file_name
        uploaded.save(path)
        if path.stat().st_size>35*1024*1024:return fail('Maximum file size is 35 MB.',413)
        try:
            kind=detect_kind(path,file_name,chosen)
            db=client()
            tables,metrics,warnings,snapshot=prepare(path,kind,month,snapshot,db,clinic_price_mode if kind=='movement' else 'historical')
            fingerprint=fingerprint_for(path,kind)
            old=db.table('report_imports').select('id,status').eq('sha256',fingerprint).limit(1).execute().data or []
            counts,conflicts=status_for(db,tables,allow_resume=bool(old and old[0]['status']=='pending'))
            if old and old[0]['status']=='imported': warnings.append('This exact file was already imported using the new uploader.')
            if kind=='movement' and any(v['changed'] for v in counts.values()):
                warnings.append('Existing movement rows have different revenue estimates or price dates. The uploader never overwrites historical records; request an administrator-reviewed repair.')
            prepared={'tables':tables,'kind':kind,'month':month,'snapshot':snapshot,'metrics':metrics,'warnings':warnings,
                      'name':file_name,'fingerprint':fingerprint,'counts':counts,'conflicts':conflicts}
            token=secrets.token_urlsafe(32)
            stage_put(db,token,g.staff['user_id'],kind,month,snapshot,file_name,fingerprint,json.loads(json.dumps(prepared)))
            return jsonify(ok=True,token=token,report_type=kind,month=month,metrics=metrics,warnings=warnings,
                           comparison=counts,conflicts=conflicts,can_accept=not bool(conflicts),
                           already_imported=bool(old and old[0]['status']=='imported'))
        except Exception as exc:
            current_app.logger.exception('Supabase upload preview failed')
            return fail('Preview failed: '+str(exc))


@bp.post('/accept')
def accept():
    body=request.get_json(silent=True) or {}
    token=body.get('token','')
    if not token:return fail('Missing preview token')
    try:
        db=client()
        draft=stage_get(db,token,g.staff['user_id'])
    except Exception:
        current_app.logger.exception('Could not read the staged preview from Supabase')
        return fail('Could not read the saved preview. Try again or upload the file again.',503)
    if not draft:return fail('Preview missing or expired. Upload again.',409)
    if dt.datetime.now(dt.timezone.utc)-dt.datetime.fromisoformat(str(draft['created_at']).replace('Z','+00:00'))>SESSION_TTL:
        return fail('Preview expired. Upload again.',409)
    prepared=draft['prepared_json']
    if isinstance(prepared,str): prepared=json.loads(prepared)
    tables=prepared['tables']
    try:
        same=db.table('report_imports').select('id,status').eq('sha256',draft['fingerprint']).limit(1).execute().data or []
        comparison,conflicts=status_for(db,tables,allow_resume=bool(same and same[0]['status']=='pending'))
        if conflicts:return fail('Saved data changed or conflicts with this report. No records written. '+ ' | '.join(conflicts),409)
        if same and same[0]['status']=='imported':
            stage_delete(db,token)
            return jsonify(ok=True,identical=True,message='This report was already imported. No duplicate created.',inserted=0)
        if all(info['new']==0 for info in comparison.values()):
            stage_delete(db,token)
            return jsonify(ok=True,identical=True,message='All records already exist with the same totals. No duplicate created.',inserted=0)
        if same and same[0]['status'] not in ('pending','validated'):
            return fail('Existing upload history needs administrator review.',409)
        if same:import_id=same[0]['id']
        else:
            imported=db.table('report_imports').insert(dict(kind=KINDS[prepared['kind']],reporting_month=prepared['month']+'-01',
                snapshot_date=prepared['snapshot'],original_filename=prepared['name'],sha256=prepared['fingerprint'],
                status='pending',source_row_count=sum(len(v) for v in tables.values()),warning_count=len(prepared['warnings']))).execute()
            import_id=imported.data[0]['id']
        inserted=0
        # Supabase jsonb does not keep key order, so insert parents before children explicitly.
        order=['products','inventory_snapshots','inventory_batches']
        ordered=sorted(tables.items(),key=lambda kv:(order.index(kv[0]) if kv[0] in order else -1))
        for table,rows in ordered:
            # Earlier pending batches may already have been inserted; only append missing identities.
            scope={}
            first=rows[0] if rows else None
            if not first:continue
            if table in ('shopee_sales_monthly','shopee_variation_sales_monthly'):
                scope={'report_month':first['report_month'],'marketplace':first['marketplace']}
            elif table=='listing_price_snapshots':scope={'snapshot_date':first['snapshot_date'],'marketplace':first['marketplace']}
            elif table in ('inventory_snapshots','inventory_batches'):scope={'snapshot_date':first['snapshot_date']}
            elif table=='products':scope={}
            else:scope={'report_month':first['report_month']}
            old=fetch_all(db,table,','.join(KEYS[table]),scope,SORT.get(table,'id'))
            old_keys={tuple(ident(v.get(k)) for k in KEYS[table]) for v in old}
            fresh=[dict(r,**({'import_id':import_id} if table not in ('shopee_variation_sales_monthly','products') else {})) for r in rows
                   if tuple(ident(r.get(k)) for k in KEYS[table]) not in old_keys]
            for start in range(0,len(fresh),100):
                db.table(table).insert(fresh[start:start+100]).execute()
                inserted+=len(fresh[start:start+100])
        db.table('report_imports').update({'status':'imported'}).eq('id',import_id).execute()
        stage_delete(db,token)
        return jsonify(ok=True,inserted=inserted,message=f'Imported {inserted} new records into Supabase.',identical=False)
    except Exception:
        current_app.logger.exception('Supabase import interrupted; pending history retained for investigation')
        return fail('Import failed or was interrupted. Some batches may be saved. Do not delete rows; contact your administrator with the Flask terminal error.',503)


@bp.get('/status')
def status():
    try:
        db=client()
        imports=fetch_all(db,'report_imports','id,kind,reporting_month,snapshot_date,original_filename,status,source_row_count,imported_at',sort='imported_at')
        summary=fetch_all(db,'v_channel_monthly_summary','report_month,channel,currency,activity_rows,units_sold,revenue,matched_rows,unmatched_rows',sort='report_month')
        inventory=fetch_all(db,'v_inventory_latest_summary','snapshot_date,total_products,products_with_snapshot,total_stock_units,total_stock_value_rm,expiry_batch_rows',sort='snapshot_date')
        return jsonify(ok=True,imports=list(reversed(imports))[:30],summary=summary,inventory=inventory[0] if inventory else None)
    except Exception:
        current_app.logger.exception('Supabase upload status failed')
        return fail('Could not load Supabase report status. Check backend log and view permissions.',503)


# Child tables that carry import_id, deleted before the import record itself.
# Batches are removed before snapshots (batches reference snapshots).
IMPORT_CHILDREN = ('inventory_batches', 'inventory_snapshots', 'clinic_movement_monthly',
                   'shopee_sales_monthly', 'listing_price_snapshots')


@bp.delete('/import/<import_id>')
def delete_import(import_id):
    """Remove one uploaded report: its rows, then the import record. Staff-only, CSRF-protected.
    A row in import_deletions (who, when, what) is written BEFORE anything is removed;
    if that record cannot be saved, nothing is deleted."""
    if not re.fullmatch(r'[0-9a-fA-F-]{36}', import_id or ''):
        return fail('Invalid import id')
    try:
        db = client()
        found = (db.table('report_imports')
                 .select('id,kind,reporting_month,snapshot_date,original_filename,source_row_count,status')
                 .eq('id', import_id).limit(1).execute().data or [])
        if not found: return fail('Import not found. Refresh the page.', 404)
        imp = found[0]
        who = g.staff.get('email') or 'unknown'
        try:
            audit = db.table('import_deletions').insert(dict(
                import_id=import_id, kind=imp['kind'], reporting_month=imp.get('reporting_month'),
                snapshot_date=imp.get('snapshot_date'), original_filename=imp.get('original_filename'),
                source_row_count=imp.get('source_row_count'), deleted_by_email=who,
                deleted_by_user_id=str(g.staff.get('user_id') or ''))).execute()
        except Exception:
            current_app.logger.exception('Could not write the deletion record; nothing was deleted')
            return fail('Could not save the deletion record, so nothing was deleted. Ask your administrator to check the import_deletions table.', 503)
        audit_id = audit.data[0]['id']
        removed = {}
        for table in IMPORT_CHILDREN:
            res = db.table(table).delete().eq('import_id', import_id).execute()
            removed[table] = len(res.data or [])
        # Variation rows have no import_id: they belong to the Shopee sales report of the same month and market.
        if imp['kind'] in ('myPerf', 'sgPerf') and imp.get('reporting_month'):
            mk = 'MY' if imp['kind'] == 'myPerf' else 'SG'
            res = (db.table('shopee_variation_sales_monthly').delete()
                   .eq('report_month', imp['reporting_month']).eq('marketplace', mk).execute())
            removed['shopee_variation_sales_monthly'] = len(res.data or [])
        db.table('report_imports').delete().eq('id', import_id).execute()
        try:
            db.table('import_deletions').update({'rows_removed': removed}).eq('id', audit_id).execute()
        except Exception:
            current_app.logger.exception('Deletion done but the row counts could not be added to the record')
        current_app.logger.warning('Import deleted by %s: %s %s %s removed=%s', who,
                                   imp['kind'], imp.get('reporting_month'), imp.get('original_filename'), removed)
        return jsonify(ok=True, removed=removed, message=f"Deleted {imp.get('original_filename') or imp['kind']} and {sum(removed.values())} saved rows. Recorded under {who}.")
    except Exception:
        current_app.logger.exception('Delete import failed')
        return fail('Delete failed or was interrupted. Some rows may already be removed. Check the history and try again, or send the Flask terminal error.', 503)


@bp.get('/deletions')
def deletions():
    """Who deleted which file, newest first."""
    try:
        db = client()
        rows = (db.table('import_deletions')
                .select('deleted_at,deleted_by_email,kind,reporting_month,original_filename,rows_removed')
                .order('deleted_at', desc=True).limit(50).execute().data or [])
        for r in rows:
            r['rows_total'] = sum((r.get('rows_removed') or {}).values())
        return jsonify(ok=True, deletions=rows)
    except Exception:
        current_app.logger.exception('Could not read the deletion log')
        return fail('Could not load the deletion log. Has the import_deletions table been created?', 503)


def register_upload_api(app):
    app.register_blueprint(bp)
