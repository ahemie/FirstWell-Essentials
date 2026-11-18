"""FirstWell Essentials Price Watch (competitor Shopee prices), merged into the Inventory app.

Routes live under /api/scrap/*. Staff login and CSRF are handled by the app's
before_request guard in app.py, so nothing here re-checks them.
Tables: fs_competitor_*, fs_scrape_*, fs_link_checks (same Supabase project).
"""
from __future__ import annotations

import datetime as dt
import html
import inspect
import json
import logging
import os
import re
import threading
import time
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from functools import wraps
from urllib.parse import unquote, urlsplit

from flask import Blueprint, g, jsonify, request
from supabase import create_client
from werkzeug.exceptions import HTTPException

from backend.scrap_lib.matching import match_detail
from backend.scrap_lib.variants import expand_variations
from backend.scrap_lib.catalog_search import search_catalog, catalog_for_product
from backend.scrap_lib.own_catalog import SOURCES, bundled_catalog, classify, read_xlsx_catalog
from backend.scrap_lib.keyword_scrape import MARKETS, clean_keyword, is_relevant, parse_listing_url, summarize

log = logging.getLogger(__name__)
bp = Blueprint('scrap_api', __name__, url_prefix='/api/scrap')
SCRAPE_LOCK = threading.Lock()
CACHE_LOCK = threading.Lock()
CATALOG_CACHE = {'until': 0.0, 'rows': []}
OWN_SHOPS = {x.strip() for x in os.getenv('OWN_SHOP_IDS', '994773440,1688602696').split(',') if x.strip()} | set(SOURCES.values())


def db():
    return create_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_SERVICE_ROLE_KEY'])


def parsed_ids(url):
    """Extract untrusted Shopee URL IDs only from genuine Malaysia HTTPS hosts."""
    if not isinstance(url, str):
        return None, None
    try:
        u = urlsplit(html.unescape(url.strip()))
        if u.scheme != 'https' or u.hostname not in ('shopee.com.my', 'www.shopee.com.my') or u.username or u.password or u.port is not None:
            return None, None
        path = unquote(u.path)
        m = re.search(r'-i\.(\d+)\.(\d+)/?$', path, re.I) or re.fullmatch(r'/product/(\d+)/(\d+)/?', path, re.I)
        return (m.group(1), m.group(2)) if m else (None, None)
    except (ValueError, TypeError):
        return None, None


def products():
    return db().table('fs_competitor_products').select('*').order('id').execute().data or []


def catalog_rows():
    """Overlay staff-updated Supabase catalog on bundled Excel reference IDs."""
    now = time.monotonic()
    with CACHE_LOCK:
        if now < CATALOG_CACHE['until']:
            return CATALOG_CACHE['rows']
    bundled = {(str(row['shop_id']), str(row['item_id'])): row for row in bundled_catalog()}
    merged = dict(bundled)
    columns = 'source,shop_id,item_id,title,variation_count,price'
    start = 0
    while True:
        try:
            page = (db().table('fs_competitor_own_catalog').select(columns)
                    .order('item_id').range(start, start+499).execute().data or [])
        except Exception:
            if columns.endswith(',price'):   # price column not created yet (schema_upgrade_stats.sql)
                columns = columns[:-6]
                continue
            raise
        for row in page:
            key = (str(row['shop_id']), str(row['item_id']))
            if row.get('price') is None and bundled.get(key, {}).get('price') is not None:
                row = {**row, 'price': bundled[key]['price']}
            if bundled.get(key, {}).get('variations'):   # variations and stock are kept in the bundled catalog only
                row = {**row, 'variations': bundled[key]['variations']}
            if bundled.get(key, {}).get('stock') is not None:
                row = {**row, 'stock': bundled[key]['stock']}
            merged[key] = row
        if len(page) < 500:
            break
        start += 500
    rows = list(merged.values())
    with CACHE_LOCK:
        CATALOG_CACHE.update(rows=rows, until=time.monotonic()+90)
    return rows


def invalidate_catalog():
    with CACHE_LOCK:
        CATALOG_CACHE['until'] = 0


def owned(shop_id, item_id, reference=None, product_list=None):
    rows = catalog_rows() if reference is None else reference
    known = set(OWN_SHOPS)
    for p in (products() if product_list is None else product_list):
        if p.get('own_shop_id'):
            known.add(str(p['own_shop_id']))
    return classify(shop_id, item_id, rows, known)


def annotate(row, reference=None, product_list=None):
    result = dict(row)
    result.update(owned(row.get('shop_id'), row.get('item_id'), reference, product_list))
    return result


@bp.get('/products')
def list_products():
    return jsonify(products=products())


@bp.post('/products')
def add_product():
    data = request.get_json(silent=True) or {}
    name = ' '.join(str(data.get('name') or '').split())[:255]
    keyword = ' '.join(str(data.get('keyword') or name).split())[:255]
    if len(name) < 3 or not keyword:
        return jsonify(error='Enter product name and search keywords'), 400
    row = {'name': name, 'keyword': keyword, 'expected_pack': str(data.get('pack') or '')[:120]}
    if data.get('our_price') not in (None, ''):
        try:
            price = Decimal(str(data['our_price']))
            if not price.is_finite() or price <= 0 or price > 99999999:
                raise ValueError()
            row['our_price'] = float(price)
        except (InvalidOperation, ValueError):
            return jsonify(error='Invalid product price'), 400
    if data.get('own_url'):
        shop, item = parsed_ids(data['own_url'])
        if not shop:
            return jsonify(error='Use a valid Shopee Malaysia product URL'), 400
        row.update(own_shop_id=shop, own_item_id=item)
    return jsonify(product=db().table('fs_competitor_products').insert(row).execute().data[0]), 201


@bp.patch('/products/<int:product_id>')
def edit_product(product_id):
    data = request.get_json(silent=True) or {}
    row = {}
    for key in ('name', 'keyword', 'expected_pack'):
        if key in data:
            row[key] = ' '.join(str(data[key]).split())[:255]
    if 'active' in data:
        row['active'] = data['active'] is True
    if 'our_price' in data:
        try:
            if data['our_price'] in ('', None):
                row['our_price'] = None
            else:
                value = Decimal(str(data['our_price']))
                if not value.is_finite() or value <= 0 or value > 99999999 or value.as_tuple().exponent < -2:
                    raise ValueError()
                row['our_price'] = float(value)
        except (InvalidOperation, ValueError):
            return jsonify(error='Invalid product price'), 400
    if 'own_url' in data:
        shop, item = parsed_ids(data['own_url'])
        if not shop:
            return jsonify(error='Invalid Shopee URL'), 400
        row.update(own_shop_id=shop, own_item_id=item)
    if not row:
        return jsonify(error='No fields to update'), 400
    return jsonify(rows=db().table('fs_competitor_products').update(row).eq('id',product_id).execute().data)


@bp.post('/products/<int:product_id>/archive')
def archive_product(product_id):
    """Hide a product from active tracking without destroying price history."""
    data = request.get_json(silent=True) or {}
    if data.get('confirm') is not True:
        return jsonify(error='Confirm removal before archiving this product'), 400
    existing = (db().table('fs_competitor_products').select('id,active')
                .eq('id', product_id).limit(1).execute().data or [])
    if not existing:
        return jsonify(error='Tracked product not found'), 404
    if not existing[0]['active']:
        return jsonify(ok=True, already_archived=True)
    db().table('fs_competitor_products').update({'active': False}).eq('id', product_id).execute()
    return jsonify(ok=True, archived_id=product_id, message='Product removed from tracking. Historical prices preserved.')


@bp.get('/catalog')
def get_catalog():
    rows = catalog_rows()
    counts = {key:sum(r['source']==key for r in rows) for key in SOURCES}
    return jsonify(counts=counts, total=len(rows), shops=SOURCES,
                   note='Product ID in the Excel is the Shopee Item ID. Variation IDs are not shop IDs.')


@bp.get('/catalog/search')
def search_own_catalog():
    query = request.args.get('q', '').strip()
    if len(query) > 200:
        return jsonify(error='Search is too long'), 400
    rows = catalog_rows()
    source = request.args.get('source', '').strip()
    if source:
        if source not in SOURCES:
            return jsonify(error='Unknown shop'), 400
        rows = [r for r in rows if r.get('source') == source]
    rows = search_catalog(rows, query)
    return jsonify(results=rows, count=len(rows),
                   note='Catalog entries are from the FirstWell and Probiotickids Excel files, not live Shopee results.')


@bp.get('/products/catalog-links')
def product_catalog_links():
    reference = catalog_rows()
    return jsonify(links={str(p['id']):catalog_for_product(reference,p) for p in products()},
                   note='Suggested links from exact product title and pack; confirm variations before relying on them.')


@bp.get('/catalog/matches')
def catalog_matches():
    try:
        pid = int(request.args.get('product_id', ''))
    except ValueError:
        return jsonify(error='Select a product'), 400
    p = next((p for p in products() if p['id']==pid), None)
    if not p:
        return jsonify(error='Product not found'),404
    selected = catalog_for_product(catalog_rows(), p)
    selected.sort(key=lambda r:(r['source'],r['title']))
    return jsonify(matches=selected[:30], total=len(selected),
                   note='These IDs come from your uploaded Excel reference, NOT a live Shopee scrape.')


def upload_catalog_rows(rows):
    for i in range(0, len(rows), 100):
        chunk = rows[i:i+100]
        try:
            db().table('fs_competitor_own_catalog').upsert(chunk, on_conflict='shop_id,item_id').execute()
        except Exception:
            if not any('price' in r for r in chunk):
                raise
            # price column not created yet: save the IDs without prices
            db().table('fs_competitor_own_catalog').upsert(
                [{k: v for k, v in r.items() if k != 'price'} for r in chunk], on_conflict='shop_id,item_id').execute()
    invalidate_catalog()


@bp.post('/catalog/sync')
def sync_bundled_catalog():
    rows = bundled_catalog()
    if not rows:
        return jsonify(error='No bundled Excel references found'), 400
    upload_catalog_rows(rows)
    return jsonify(ok=True, synced=len(rows), message='Excel product IDs synced to Supabase')


@bp.post('/catalog/upload/<source>')
def upload_catalog(source):
    file = request.files.get('file')
    if not file or not file.filename or not file.filename.lower().endswith('.xlsx'):
        return jsonify(error='Choose a Shopee Mass Update XLSX file'),400
    try:
        rows = read_xlsx_catalog(file.read(), source)
    except (ValueError, KeyError, OSError) as exc:
        return jsonify(error=str(exc)),400
    upload_catalog_rows(rows)
    return jsonify(ok=True, source=source, imported=len(rows))


@bp.get('/listings')
def listings():
    query = db().table('fs_competitor_listings').select('*').order('collected_at', desc=True).limit(1000)
    if request.args.get('product_id'):
        try:
            query = query.eq('product_id', int(request.args['product_id']))
        except ValueError:
            return jsonify(error='Invalid product filter'),400
    rows = query.execute().data or []
    ref, ps = catalog_rows(), products()
    for i,row in enumerate(rows):
        rows[i] = annotate(row, ref, ps)
    return jsonify(listings=rows)


def build_price_overview(ps, rows, ref):
    """Summarize ONLY matching, manually approved, non-owned listings.

    Latest price statistics use the newest approved date for each product.
    Older snapshots are included in the historical trend, never as current prices.
    """
    result = []
    approved_total = 0
    from datetime import date as _date
    today = _date.today()
    for p in ps:
        if not p.get('active', True):
            continue
        eligible = [r for r in rows if r.get('product_id') == p['id']
                    and r.get('status') == 'APPROVE'
                    and not owned(r.get('shop_id'),r.get('item_id'),ref,ps)['own_shop']
                    and match_detail(r.get('title') or '',p['keyword'],p.get('expected_pack') or '')[0]
                    and r.get('snapshot_date') and r.get('price') is not None]
        approved_total += len(eligible)
        latest = max((str(r['snapshot_date']) for r in eligible),default=None)
        current = [float(r['price']) for r in eligible if str(r['snapshot_date'])==latest]
        own_price = float(p['our_price']) if p.get('our_price') is not None else None
        lowest = min(current) if current else None
        average = round(sum(current)/len(current),2) if current else None
        highest = max(current) if current else None
        gap = round(own_price - lowest,2) if own_price is not None and lowest is not None else None
        gap_pct = round(100*gap/lowest,2) if gap is not None and lowest else None
        by_date = {}
        for r in eligible:
            date = str(r['snapshot_date'])
            by_date.setdefault(date,[]).append(float(r['price']))
        history = [{'date':date,'lowest':min(values),
                    'average':round(sum(values)/len(values),2),
                    'highest':max(values),'count':len(values)}
                   for date,values in sorted(by_date.items())]
        age_days = (today - _date.fromisoformat(latest)).days if latest else None
        if gap is None:
            action = 'ADD_OUR_PRICE' if own_price is None else 'REVIEW_COMPETITORS'
        elif age_days is not None and age_days > 30:
            action = 'REFRESH_SNAPSHOT'
        elif gap > 0:
            action = 'PRICE_RISK'
        elif gap < 0:
            action = 'PRICE_ADVANTAGE'
        else:
            action = 'AT_PAR'
        result.append({'product':p,'approved':len(eligible),'current_count':len(current),
                       'age_days':age_days,'action':action,
                       'snapshot_date':latest,'lowest':lowest,'average':average,'highest':highest,
                       'gap_rm':gap,'gap_percent':gap_pct,'history':history})
    compared = [r for r in result if r['gap_rm'] is not None]
    return {'products':result,'total_listings':len(rows),'approved':approved_total,
            'pending':sum(r.get('status')=='REVIEW' for r in rows),
            'products_compared':len(compared),
            'priced_above_lowest':sum(r['gap_rm']>0 for r in compared),
            'priced_below_lowest':sum(r['gap_rm']<0 for r in compared),
            'missing_comparison':len(result)-len(compared),
            'stale_products':sum(r['age_days'] is not None and r['age_days']>30 for r in result),
            'as_of':today.isoformat(),
            'average_gap_rm':round(sum(r['gap_rm'] for r in compared)/len(compared),2) if compared else None,
            'note':'Approved matching competitor snapshots only; historical prices are not live offers.'}


@bp.get('/overview')
def overview():
    ps=products()
    ref=catalog_rows()
    # Supabase paginates larger result sets. Page through every record to avoid
    # inaccurate summary metrics when more than 1,000 rows exist.
    rows=[]
    for offset in range(0,100000,1000):
        batch=(db().table('fs_competitor_listings')
               .select('product_id,price,status,shop_id,item_id,snapshot_date,title')
               .order('id').range(offset,offset+999).execute().data or [])
        rows.extend(batch)
        if len(batch)<1000:
            break
    return jsonify(build_price_overview(ps,rows,ref))


@bp.post('/listings/<int:listing_id>/decision')
def decision(listing_id):
    data = request.get_json(silent=True) or {}
    status = str(data.get('status','')).upper()
    if status not in {'APPROVE','REVIEW','EXCLUDE','UNAVAILABLE'}:
        return jsonify(error='Invalid review decision'),400
    result=db().table('fs_competitor_listings').select('*').eq('id',listing_id).limit(1).execute().data
    if not result:
        return jsonify(error='Listing not found'),404
    row=result[0]
    classification=owned(row.get('shop_id'),row.get('item_id'))
    if status=='APPROVE':
        if data.get('verified') is not True:
            return jsonify(error='Confirm exact product, pack, variation and price before approving'),400
        if not row.get('shop_id') or classification['own_shop'] or classification['own_match']=='ID_CONFLICT':
            return jsonify(error='Cannot approve our shop or unidentified/conflicting Shop ID'),400
        p=next((x for x in products() if x['id']==row['product_id']),None)
        if not p or not match_detail(row['title'],p['keyword'],p.get('expected_pack') or '')[0]:
            return jsonify(error='Product name or pack does not match; leave as REVIEW or EXCLUDE'),400
    payload={'status':status,'verified_by':g.staff['user_id'],
             'reviewed_at':dt.datetime.now(dt.timezone.utc).isoformat()}
    saved=db().table('fs_competitor_listings').update(payload).eq('id',listing_id).execute().data
    return jsonify(row=annotate(saved[0]))


@bp.get('/jobs')
def jobs():
    return jsonify(jobs=db().table('fs_competitor_jobs').select('*').order('started_at',desc=True).limit(30).execute().data)


@bp.get('/jobs/<int:job_id>/results')
def job_results(job_id):
    jobs=db().table('fs_competitor_jobs').select('*').eq('id',job_id).limit(1).execute().data
    if not jobs:
        return jsonify(error='Scraping job not found'),404
    rows=(db().table('fs_competitor_listings').select('*').eq('last_job_id',job_id)
          .order('result_rank').limit(10).execute().data or [])
    ref, ps=catalog_rows(),products()
    return jsonify(job=jobs[0],listings=[annotate(r,ref,ps) for r in rows])


def _price(value):
    if isinstance(value,dict):
        value=value.get('value') or value.get('price')
    cleaned=re.sub(r'(?i)rm\s*|s\$\s*|\$|,|\s+', '',str(value or ''))
    try:
        price=Decimal(cleaned)
        return price if price.is_finite() and 0<price<=99999999 else None
    except InvalidOperation:
        return None


def _count(value):
    """Parse counts such as 1234, '1,234', '1.2k', '10k+' or '1.5m' into an integer (None if unknown)."""
    if value is None or isinstance(value,bool):
        return None
    if isinstance(value,(int,float)):
        return int(value) if value>=0 else None
    text=str(value).strip().lower().replace(',','')
    m=re.match(r'^(\d+(?:\.\d+)?)\s*([km]|rb|jt)?\+?(?:\s*sold)?$',text)
    if not m:
        return None
    factor={'k':1000,'rb':1000,'m':1000000,'jt':1000000}.get(m.group(2),1)
    return int(round(float(m.group(1))*factor))


def _number(value,low=0,high=99999999):
    try:
        n=float(str(value).replace(',',''))
    except (TypeError,ValueError):
        return None
    return round(n,2) if low<=n<=high else None


def _item_stats(item):
    """Optional market signals returned by the Apify actor; absent values stay out of the row."""
    pick=lambda *keys: next((item[k] for k in keys if item.get(k) is not None),None)
    price=_price(pick('original_price','price_before_discount'))
    loc=pick('location','shop_location')
    stats={'rating':_number(pick('rating','rating_star','item_rating'),0,5),
           'rating_count':_count(pick('rating_count','ratingCount','review_count','rating_total')),
           'sold_count':_count(pick('sold_count','sold','historical_sold','total_sold')),
           'original_price':float(price) if price is not None else None,
           'discount_pct':_number(pick('discount_pct','discount'),0,100),
           'location':str(loc)[:100] if isinstance(loc,str) and loc.strip() else None}
    return {k:v for k,v in stats.items() if v is not None}


def _save_scraped_item(item, product, job_id, rank, ref, ps):
    title=item.get('name') or item.get('title') or item.get('product_name') or ''
    url=item.get('url') or item.get('product_url') or item.get('link') or ''
    shop, item_id=parsed_ids(url)
    good,reason=match_detail(title,product['keyword'],product.get('expected_pack') or '')
    price=_price(item.get('price'))
    if not good or not shop or not item_id or price is None:
        return False
    classification=owned(shop,item_id,ref,ps)
    raw_seller=item.get('shop_name') or item.get('seller_name') or item.get('seller')
    if isinstance(raw_seller,dict):
        raw_seller=raw_seller.get('name')
    if not raw_seller and isinstance(item.get('shop'),dict):
        raw_seller=item['shop'].get('name')
    stats=_item_stats(item)
    date=datetime.now(timezone.utc).date().isoformat()
    existing=(db().table('fs_competitor_listings').select('id').eq('product_id',product['id'])
              .eq('url',url[:500]).eq('snapshot_date',date).limit(1).execute().data or [])
    if existing:
        # Preserve staff decisions and historical prices; link this existing row to the new job.
        db().table('fs_competitor_listings').update({'last_job_id':job_id,'result_rank':rank}).eq('id',existing[0]['id']).execute()
        if stats:
            try:
                db().table('fs_competitor_listings').update(stats).eq('id',existing[0]['id']).execute()
            except Exception:
                pass  # statistics columns not created yet (schema_upgrade_stats.sql)
    else:
        row={'product_id':product['id'],'shop_id':shop,'item_id':item_id,
             'seller_name':str(raw_seller)[:255] if raw_seller else None,
             'title':str(title)[:2000], 'url':str(url)[:500], 'price':float(price),
             'status':'EXCLUDE' if classification['own_shop'] else 'REVIEW',
             'match_hint':reason, 'snapshot_date':date, 'last_job_id':job_id,
             'result_rank':rank}
        try:
            db().table('fs_competitor_listings').insert({**row,**stats}).execute()
        except Exception:
            if not stats:
                raise
            db().table('fs_competitor_listings').insert(row).execute()  # columns missing: save without statistics
    return True


def parse_apify_limits(payload):
    """Turn Apify's /users/me/limits response into the few numbers staff need. Raises ValueError when the shape is wrong."""
    try:
        data = payload['data']
        used = float(data['current']['monthlyUsageUsd'])
        limit = float(data['limits']['maxMonthlyUsageUsd'])
        cycle_end = data.get('monthlyUsageCycle', {}).get('endAt')
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError('Unexpected response from Apify') from exc
    return {'used_usd': round(used, 4), 'limit_usd': round(limit, 4),
            'remaining_usd': round(max(limit - used, 0), 4), 'cycle_ends': cycle_end}


def apify_usage():
    """Monthly Apify credit now, or None if there is no token or Apify cannot be reached. The token is never returned."""
    token = os.getenv('APIFY_TOKEN')
    if not token:
        return None
    try:
        req = urllib.request.Request('https://api.apify.com/v2/users/me/limits', headers={'Authorization': 'Bearer ' + token})
        with urllib.request.urlopen(req, timeout=8) as response:
            return parse_apify_limits(json.loads(response.read().decode('utf-8')))
    except Exception:
        log.warning('Could not read Apify usage')
        return None


def run_cost_usd(result):
    """Cost of one finished Apify run in USD, or None if the run object does not say."""
    value = None
    if isinstance(result, dict):
        value = result.get('usageTotalUsd', result.get('usage_total_usd'))
    elif result is not None:
        value = getattr(result, 'usage_total_usd', None)
    try:
        return None if value is None else round(float(value), 4)
    except (TypeError, ValueError):
        return None


def money_usd(value):
    if value is None:
        return 'unknown'
    return f'${value:.3f}' if 0 < value < 0.1 else f'${value:.2f}'


@bp.get('/apify/usage')
def apify_usage_route():
    cap = float(os.getenv('MAX_CHARGE_PER_RUN_USD', '0.25'))
    if not os.getenv('APIFY_TOKEN'):
        return jsonify(configured=False, cap_usd=cap)
    usage = apify_usage()
    if usage is None:
        return jsonify(configured=True, available=False, cap_usd=cap,
                       message='Could not read your Apify credit right now. You can still scrape; try Refresh in a minute.')
    return jsonify(configured=True, available=True, cap_usd=cap, **usage)



def collect_worker(product, job_id):
    saved=0
    scanned=0
    status='FAILED'
    message=''
    extras={}
    try:
        from apify_client import ApifyClient
        token=os.environ['APIFY_TOKEN']
        limit=max(1,min(int(os.getenv('MAX_RESULTS_PER_PRODUCT','10')),10))
        pool=max(limit,min(int(os.getenv('SEARCH_CANDIDATES_PER_RUN','30')),50))
        cap=float(os.getenv('MAX_CHARGE_PER_RUN_USD','0.25'))
        client=ApifyClient(token)
        before=apify_usage()
        if before:
            extras['credit_before_usd']=before['remaining_usd']
        result=client.actor(os.getenv('APIFY_ACTOR_ID','xtracto/shopee-search')).call(
            run_input={'country':'my','mode':'keyword','keyword':product['keyword'],
                       'sort':'sales','maxProducts':pool,'fetchDetail':False},
            max_items=pool,max_total_charge_usd=cap)
        extras['cost_usd']=run_cost_usd(result)
        run_status = (result.get('status') if isinstance(result, dict) else getattr(result, 'status', None)) if result else None
        if getattr(run_status, 'value', run_status) != 'SUCCEEDED':
            raise RuntimeError('Apify Actor did not complete successfully')
        dataset_id = (result.get('defaultDatasetId') if isinstance(result, dict) else getattr(result, 'default_dataset_id', None))
        if not dataset_id:
            raise RuntimeError('Apify run returned no dataset ID')
        raw=client.dataset(dataset_id).list_items(limit=pool).items
        ref, ps=catalog_rows(), products()
        for item in raw:
            scanned+=1
            if saved>=limit:
                break
            if not isinstance(item,dict):
                continue
            if _save_scraped_item(item,product,job_id,saved+1,ref,ps):
                saved+=1
        status='COMPLETED'
        message=(f'Scanned {scanned} Shopee search results; found {saved} matching listings. '
                 'Requested Shopee best-selling order (sales); matching product and pack filters still apply. Our shops are included and labelled, not counted as competitors. '
                 'Fewer than 10 means fewer matching listings were returned.')
    except Exception as exc:
        message=f'{type(exc).__name__}: {str(exc)[:220]}'
    finally:
        try:
            after=apify_usage()
            if after:
                extras['credit_after_usd']=after['remaining_usd']
            if 'cost_usd' in extras or 'credit_after_usd' in extras:
                left=f" Credit left {money_usd(after['remaining_usd'])}." if after else ''
                message=(message+f" Apify cost {money_usd(extras.get('cost_usd'))}."+left).strip()
            base={'status':status,'finished_at':dt.datetime.now(dt.timezone.utc).isoformat(),
                  'candidate_count':scanned,'saved_count':saved,'message':message}
            try:
                db().table('fs_competitor_jobs').update({**base,**{k:v for k,v in extras.items() if v is not None}}).eq('id',job_id).execute()
            except Exception:
                # cost columns not added yet (schema_upgrade_usage.sql): still save the job; cost stays in the message
                db().table('fs_competitor_jobs').update(base).eq('id',job_id).execute()
        finally:
            SCRAPE_LOCK.release()


@bp.post('/scrape')
def scrape():
    data=request.get_json(silent=True) or {}
    if data.get('confirm_paid') is not True:
        return jsonify(error='Confirm potentially paid Apify collection'),400
    if not os.getenv('APIFY_TOKEN'):
        return jsonify(error='Add APIFY_TOKEN to your private .env file'),400
    try:
        product_id=int(data.get('product_id'))
    except (TypeError,ValueError):
        return jsonify(error='Select a tracked product'),400
    p=next((x for x in products() if x['id']==product_id and x['active']),None)
    if not p:
        return jsonify(error='Product not found or inactive'),404
    previous=(db().table('fs_competitor_jobs').select('started_at').eq('product_id',product_id)
              .order('started_at',desc=True).limit(1).execute().data or [])
    if previous:
        when=dt.datetime.fromisoformat(previous[0]['started_at'].replace('Z','+00:00'))
        if (dt.datetime.now(dt.timezone.utc)-when).total_seconds()<300:
            return jsonify(error='Please wait 5 minutes before repeating this product scrape'),429
    if not SCRAPE_LOCK.acquire(False):
        return jsonify(error='Another scrape is already in progress'),409
    try:
        job=db().table('fs_competitor_jobs').insert({
            'product_id':product_id,'status':'STARTED','requested_by':g.staff['user_id']}).execute().data[0]
        threading.Thread(target=collect_worker,args=(p,job['id']),daemon=True).start()
        return jsonify(job_id=job['id'],message='Paid scraping started. Results will appear under Top 10.'),202
    except Exception:
        SCRAPE_LOCK.release()
        raise


# ---------------------------------------------------------------------------
# Keyword scrape page (Scrape + Results): one synchronous Apify run per request.
# ---------------------------------------------------------------------------
SETUP_MSG = 'Run schema_scrape_runs.sql once in the Supabase SQL Editor. It creates the tables for this page.'


def needs_runs_tables(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            if 'fs_scrape' in str(exc):
                log.warning('Scrape tables missing: %s', exc)
                return jsonify(error=SETUP_MSG), 503
            raise
    return wrapped


@bp.get('/catalog/list')
def catalog_list():
    source = request.args.get('source', 'Probiotickids').strip()
    if source not in SOURCES:
        return jsonify(error='Unknown shop'), 400
    rows = [{k: r.get(k) for k in ('source', 'shop_id', 'item_id', 'title', 'price', 'variation', 'variation_id', 'stock')}
            for r in expand_variations([x for x in catalog_rows() if x.get('source') == source])]
    rows.sort(key=lambda r: str(r['title']).casefold())
    return jsonify(products=rows, count=len(rows))


def normalise_result(item, market, keyword, ref, ps):
    """One Apify item -> a result row, or None when it has no usable title, URL, IDs or price."""
    if not isinstance(item, dict):
        return None
    title = str(item.get('name') or item.get('title') or item.get('product_name') or '').strip()
    url = item.get('url') or item.get('product_url') or item.get('link') or ''
    shop, item_id = parse_listing_url(url, market)
    price = _price(item.get('price'))
    if not title or not shop or not item_id or price is None:
        return None
    raw_seller = item.get('shop_name') or item.get('seller_name') or item.get('seller')
    if isinstance(raw_seller, dict):
        raw_seller = raw_seller.get('name')
    if not raw_seller and isinstance(item.get('shop'), dict):
        raw_seller = item['shop'].get('name')
    is_own = bool(owned(shop, item_id, ref, ps)['own_shop'])
    relevant = is_relevant(title, keyword)
    return {'item_id': item_id, 'shop_id': shop, 'seller_name': str(raw_seller)[:255] if raw_seller else None,
            'title': title[:2000], 'url': str(url)[:500], 'price': float(price), 'is_own': is_own,
            'relevant': relevant, 'included': relevant and not is_own, **_item_stats(item)}


def fetch_shopee(keyword, market):
    """Run the Apify actor and wait for it. Returns (raw items, run cost in USD)."""
    from apify_client import ApifyClient
    pool = max(1, min(int(os.getenv('SEARCH_CANDIDATES_PER_RUN', '30')), 50))
    cap = float(os.getenv('MAX_CHARGE_PER_RUN_USD', '0.25'))
    client = ApifyClient(os.environ['APIFY_TOKEN'])
    actor = client.actor(os.getenv('APIFY_ACTOR_ID', 'xtracto/shopee-search'))
    limit = int(os.getenv('APIFY_TIMEOUT_SECS', '75'))
    # apify-client 2.x names this timeout_secs (int); 3.x names it run_timeout (timedelta). Support both.
    wanted = inspect.signature(actor.call).parameters
    timeout_arg = {'run_timeout': dt.timedelta(seconds=limit)} if 'run_timeout' in wanted else {'timeout_secs': limit} if 'timeout_secs' in wanted else {}
    result = actor.call(
        run_input={'country': MARKETS[market]['country'], 'mode': 'keyword', 'keyword': keyword,
                   'sort': os.getenv('SCRAPE_SORT', 'sales'), 'maxProducts': pool, 'fetchDetail': False},
        max_items=pool, max_total_charge_usd=cap, **timeout_arg)
    cost = run_cost_usd(result)
    status = (result.get('status') if isinstance(result, dict) else getattr(result, 'status', None)) if result else None
    if getattr(status, 'value', status) != 'SUCCEEDED':
        raise RuntimeError('Apify did not finish this search. Try again in a minute.')
    dataset_id = result.get('defaultDatasetId') if isinstance(result, dict) else getattr(result, 'default_dataset_id', None)
    if not dataset_id:
        raise RuntimeError('Apify returned no results dataset')
    return client.dataset(dataset_id).list_items(limit=pool).items, cost


@bp.post('/scrape-keyword')
@needs_runs_tables
def scrape_keyword():
    data = request.get_json(silent=True) or {}
    keyword = clean_keyword(data.get('keyword'))
    market = str(data.get('market', '')).upper()
    if not keyword:
        return jsonify(error='Type a keyword first (at least 2 letters).'), 400
    if market not in MARKETS:
        return jsonify(error='Choose Shopee Malaysia or Shopee Singapore.'), 400
    if not os.getenv('APIFY_TOKEN'):
        return jsonify(error='Add APIFY_TOKEN to your private .env file (or the Vercel environment variables).'), 400
    product_name = str(data.get('product_name') or '').strip()[:300] or None
    product_item = re.sub(r'\D', '', str(data.get('product_item_id') or ''))[:20] or None
    our_price = _number(data.get('our_price'), 0.01, 99999999) if data.get('our_price') not in (None, '') else None
    previous = (db().table('fs_scrape_runs').select('id,started_at').eq('keyword', keyword).eq('market', market)
                .order('started_at', desc=True).limit(1).execute().data or [])
    if previous:
        when = dt.datetime.fromisoformat(previous[0]['started_at'].replace('Z', '+00:00'))
        if (dt.datetime.now(dt.timezone.utc) - when).total_seconds() < 300:
            return jsonify(error='This keyword was scraped less than 5 minutes ago, so no new credit was used. Showing that result.',
                           run_id=previous[0]['id']), 429
    if not SCRAPE_LOCK.acquire(False):
        return jsonify(error='Another scrape is running. Wait a moment and try again.'), 409
    run = None
    try:
        run = db().table('fs_scrape_runs').insert({
            'keyword': keyword, 'market': market, 'currency': MARKETS[market]['currency'], 'product_name': product_name,
            'product_item_id': product_item, 'our_price': our_price, 'status': 'STARTED',
            'requested_by': str(g.staff.get('email', ''))[:200]}).execute().data[0]
        scanned, cost, rows = 0, None, []
        try:
            raw, cost = fetch_shopee(keyword, market)
            ref, ps = catalog_rows(), products()
            seen = set()
            for item in raw:
                scanned += 1
                row = normalise_result(item, market, keyword, ref, ps)
                if row and row['item_id'] not in seen:
                    seen.add(row['item_id'])
                    rows.append(row)
            rows.sort(key=lambda r: r['price'])
            for i, row in enumerate(rows, 1):
                row['run_id'], row['rank'] = run['id'], i
            saved = []
            for i in range(0, len(rows), 100):
                saved += db().table('fs_scrape_results').insert(rows[i:i+100]).execute().data or []
            stats = summarize(saved or rows)
            update = {'status': 'COMPLETED', 'scanned_count': scanned, 'result_count': len(rows), **stats,
                      'cost_usd': cost, 'finished_at': dt.datetime.now(dt.timezone.utc).isoformat(),
                      'message': f"Scanned {scanned} Shopee results, kept {len(rows)} with a price, {stats['included_count']} counted as the same product."
                                 f" Apify cost {money_usd(cost)}."}
            run = db().table('fs_scrape_runs').update(update).eq('id', run['id']).execute().data[0]
            return jsonify(run=run, results=saved or rows)
        except Exception as exc:
            message = f'{type(exc).__name__}: {str(exc)[:220]}'
            log.warning('Keyword scrape failed: %s', message)
            db().table('fs_scrape_runs').update({'status': 'FAILED', 'message': message, 'scanned_count': scanned,
                                                 'finished_at': dt.datetime.now(dt.timezone.utc).isoformat()}).eq('id', run['id']).execute()
            return jsonify(error=message, run_id=run['id']), 502
    finally:
        SCRAPE_LOCK.release()


@bp.get('/runs')
@needs_runs_tables
def list_runs():
    rows = db().table('fs_scrape_runs').select('*').order('started_at', desc=True).limit(60).execute().data or []
    return jsonify(runs=rows)


@bp.get('/runs/<int:run_id>')
@needs_runs_tables
def get_run(run_id):
    run = (db().table('fs_scrape_runs').select('*').eq('id', run_id).limit(1).execute().data or [None])[0]
    if not run:
        return jsonify(error='Scrape not found'), 404
    results = db().table('fs_scrape_results').select('*').eq('run_id', run_id).order('price').execute().data or []
    return jsonify(run=run, results=results)


@bp.patch('/runs/<int:run_id>/results/<int:result_id>')
@needs_runs_tables
def set_included(run_id, result_id):
    data = request.get_json(silent=True) or {}
    if not isinstance(data.get('included'), bool):
        return jsonify(error='included must be true or false'), 400
    row = (db().table('fs_scrape_results').select('*').eq('id', result_id).eq('run_id', run_id).limit(1).execute().data or [None])[0]
    if not row:
        return jsonify(error='Result not found'), 404
    included = data['included'] and not row.get('is_own')   # our own shop can never count as a competitor
    db().table('fs_scrape_results').update({'included': included}).eq('id', result_id).execute()
    results = db().table('fs_scrape_results').select('*').eq('run_id', run_id).execute().data or []
    run = db().table('fs_scrape_runs').update(summarize(results)).eq('id', run_id).execute().data[0]
    return jsonify(run=run, included=included)


LINK_SETUP_MSG = 'Run schema_link_checks.sql once in the Supabase SQL Editor. It creates the table for this page.'
LINK_KEY = re.compile(r'^\d{6,20}(_\d{4,24})?$')


def needs_link_table(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            if 'fs_link_checks' in str(exc):
                log.warning('Link check table missing: %s', exc)
                return jsonify(error=LINK_SETUP_MSG), 503
            raise
    return wrapped


@bp.get('/link-checks')
@needs_link_table
def list_link_checks():
    rows = db().table('fs_link_checks').select('product_key,status,checked_by,checked_at').limit(5000).execute().data or []
    return jsonify(checks={r['product_key']: {'s': r['status'], 'by': r.get('checked_by'), 'at': r.get('checked_at')} for r in rows})


@bp.put('/link-checks/<key>')
@needs_link_table
def set_link_check(key):
    if not LINK_KEY.match(key):
        return jsonify(error='Unknown product'), 400
    status = (request.get_json(silent=True) or {}).get('status')
    if status not in ('ok', 'bad', ''):
        return jsonify(error='status must be ok, bad or empty'), 400
    if status == '':
        db().table('fs_link_checks').delete().eq('product_key', key).execute()
        return jsonify(check=None)
    row = {'product_key': key, 'status': status, 'checked_by': g.staff.get('email'),
           'checked_at': datetime.now(timezone.utc).isoformat()}
    db().table('fs_link_checks').upsert(row, on_conflict='product_key').execute()
    return jsonify(check={'s': status, 'by': row['checked_by'], 'at': row['checked_at']})



@bp.errorhandler(Exception)
def on_error(error):
    if isinstance(error, HTTPException):   # 404, 405 and friends keep their own status
        return error
    log.exception('Price Watch request failed')
    code = getattr(error, 'code', None)
    if type(error).__name__ == 'APIError' and (str(code).startswith('5') or 'timed out' in str(error).lower()):
        return jsonify(error='The database (Supabase) did not answer in time. This is usually temporary: wait a minute and try again. If it keeps happening, open the Supabase dashboard and check the project is not paused.'), 503
    return jsonify(error='Server error; please try again.'), 500


def register_scrap_api(app):
    app.register_blueprint(bp)
