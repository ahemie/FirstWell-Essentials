"""Shopee listing -> Avixo product links, uploaded from the review workbook (sheet "Links").

POST /api/links/preview  (multipart: file, market)  -> what would change, nothing written
POST /api/links/save     (multipart: file, market)  -> saves links and re-matches sales already uploaded

How links are stored: product_channel_links keeps dated sets; the sales uploader uses only the NEWEST
observed_on date. Saving therefore writes a complete new set dated today: the previous newest set, with every
Shopee item that appears (filled in) in the workbook replaced by the workbook rows.
Column "Avixo ID to use": an Avixo ID links the row; FREE marks a free gift (listing_flags); empty = skip.
IDs starting with FS- are FirstStep Avixo products (stock kept at FirstStep). They are created in this database as
products (category "FirstStep stock") from the sheet "Avixo products" the first time they are used.
"""
import datetime as dt
import uuid as uuidlib
import tempfile
from collections import defaultdict
from pathlib import Path

import openpyxl
from flask import Blueprint, current_app, g, jsonify, request
from werkzeug.utils import secure_filename

from backend.supabase_upload import client, fetch_all, ident, fail

bp = Blueprint('shopee_links', __name__, url_prefix='/api/links')
KL = dt.timezone(dt.timedelta(hours=8))
COLS = {'market': 'Marketplace', 'item': 'Shopee item ID', 'var': 'Variation ID',
        'name': 'Shopee product name', 'use': 'Avixo ID to use'}


def read_links_workbook(path, market):
    """Returns (rows, problems). rows: dicts with item, var, avixo (or 'FREE'), name."""
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb['Links'] if 'Links' in wb.sheetnames else wb.worksheets[0]
    it = ws.iter_rows(values_only=True)
    header = None
    for r in it:
        names = [str(x or '').strip() for x in r]
        if COLS['item'] in names and COLS['use'] in names:
            header = {n: i for i, n in enumerate(names) if n}
            break
    if header is None:
        raise ValueError('This is not the Shopee links sheet: columns "Shopee item ID" and "Avixo ID to use" were not found.')
    get = lambda r, key: r[header[COLS[key]]] if COLS[key] in header and header[COLS[key]] < len(r) else None
    rows, problems, seen = [], [], {}
    for n, r in enumerate(it, start=2):
        use = ident(get(r, 'use'))
        if not use:
            continue
        m = str(get(r, 'market') or market).strip().upper()
        if m != market:
            problems.append(f'Row {n}: marketplace {m} does not match the selected {market}')
            continue
        item, var = ident(get(r, 'item')), ident(get(r, 'var')) or '0'
        if not item.isdigit() or not var.isdigit():
            problems.append(f'Row {n}: Shopee item/variation ID is not a number')
            continue
        avixo = 'FREE' if use.upper() == 'FREE' else use
        key = (item, var)
        if key in seen and seen[key] != avixo:
            problems.append(f'Row {n}: listing {item}/{var} has two different Avixo IDs ({seen[key]} and {avixo})')
            continue
        seen[key] = avixo
        rows.append(dict(item=item, var=var, avixo=avixo, name=str(get(r, 'name') or '').strip()))
    # A listing must be linked either as a whole (variation 0) or per variation, not both.
    by_item = defaultdict(set)
    for x in rows:
        by_item[x['item']].add(x['var'])
    for item, vars_ in by_item.items():
        if '0' in vars_ and len(vars_) > 1:
            problems.append(f'Listing {item}: has a whole-listing row and variation rows; keep only one kind')
    extra = {}
    if 'Avixo products' in wb.sheetnames:
        for r in wb['Avixo products'].iter_rows(min_row=2, values_only=True):
            pid = ident(r[0] if r else None)
            if pid.upper().startswith('FS-') and len(r) > 1 and r[1]:
                extra[pid.upper()] = str(r[1]).strip()[:200]
    for x in rows:
        if x['avixo'].upper().startswith('FS-'):
            x['avixo'] = x['avixo'].upper()
    wb.close()
    return rows, problems, extra


def newest_set(db, market):
    links = fetch_all(db, 'product_channel_links', 'marketplace,shopee_item_id,shopee_variation_id,product_id,observed_on',
                      {'marketplace': market})
    if not links:
        return {}, None
    newest = max(str(x['observed_on']) for x in links)
    return ({(ident(x['shopee_item_id']), ident(x['shopee_variation_id']) or '0'): x['product_id']
             for x in links if str(x['observed_on']) == newest}, newest)


def lookups(link_set):
    owners = defaultdict(set)
    parents = defaultdict(list)
    for (item, var), pid in link_set.items():
        owners[(item, var)].add(pid)
        parents[item].append((var, pid))
    exact = {k: next(iter(v)) for k, v in owners.items() if len(v) == 1}
    only_parent = {item: vs[0][1] for item, vs in parents.items()
                   if {v for v, _ in vs} == {'0'} and len({p for _, p in vs}) == 1}
    return exact, only_parent


def plan(db, rows, market, extra=None):
    products = fetch_all(db, 'products', 'id,avixo_id,name', sort='avixo_id')
    by_avixo = {ident(p['avixo_id']): p for p in products}
    new_products = []
    for avixo in sorted({x['avixo'] for x in rows if x['avixo'].startswith('FS-')} - set(by_avixo)):
        if avixo in (extra or {}):
            p = dict(id=str(uuidlib.uuid4()), avixo_id=avixo, name=extra[avixo], category='FirstStep stock')
            new_products.append(p)
            by_avixo[avixo] = p
    unknown = sorted({x['avixo'] for x in rows if x['avixo'] != 'FREE' and x['avixo'] not in by_avixo})
    old, old_date = newest_set(db, market)
    touched = {x['item'] for x in rows}
    new = {k: v for k, v in old.items() if k[0] not in touched}
    free = {}
    for x in rows:
        if x['avixo'] == 'FREE':
            free[x['item']] = x['name']
        elif x['avixo'] in by_avixo:
            new[(x['item'], x['var'])] = by_avixo[x['avixo']]['id']
    exact, only_parent = lookups(new)
    parents = fetch_all(db, 'shopee_sales_monthly', 'id,shopee_item_id,product_id,mapping_status', {'marketplace': market})
    variations = fetch_all(db, 'shopee_variation_sales_monthly', 'id,shopee_item_id,shopee_variation_id,product_id',
                           {'marketplace': market})
    p_updates, v_updates = defaultdict(list), defaultdict(list)
    for r in parents:
        want = only_parent.get(ident(r['shopee_item_id']))
        if want != r.get('product_id'):
            p_updates[want].append(r['id'])
    for r in variations:
        item, var = ident(r['shopee_item_id']), ident(r['shopee_variation_id']) or '0'
        want = exact.get((item, var)) or only_parent.get(item)
        if want != r.get('product_id'):
            v_updates[want].append(r['id'])
    flagged = {ident(f['shopee_item_id']) for f in fetch_all(db, 'listing_flags', 'shopee_item_id', {'marketplace': market},
                                                             'shopee_item_id')} | set(free)
    var_items = {ident(r['shopee_item_id']) for r in variations}
    # Same rule as the reporting view: an item with variation rows is reported through its variations.
    still = (sum(1 for r in parents if ident(r['shopee_item_id']) not in var_items | flagged
                 and not only_parent.get(ident(r['shopee_item_id']))),
             sum(1 for r in variations if ident(r['shopee_item_id']) not in flagged
                 and not (exact.get((ident(r['shopee_item_id']), ident(r['shopee_variation_id']) or '0'))
                          or only_parent.get(ident(r['shopee_item_id'])))))
    summary = dict(rows_in_file=len(rows), links_before=len(old), links_after=len(new),
                   listings_in_file=len(touched), free_items=len(free), unknown_avixo_ids=unknown,
                   sales_rows_rematched=sum(len(v) for v in p_updates.values()) + sum(len(v) for v in v_updates.values()),
                   sales_parent_rows_unmapped_after=still[0], sales_variation_rows_unmapped_after=still[1],
                   previous_links_date=old_date, firststep_products_added=len(new_products))
    return summary, new, free, p_updates, v_updates, new_products


def _with_file(handler):
    market = request.form.get('market', 'MY').strip().upper()
    if market not in ('MY', 'SG'):
        return fail('Choose MY or SG.')
    uploaded = request.files.get('file')
    if not uploaded or not uploaded.filename or Path(uploaded.filename).suffix.lower() != '.xlsx':
        return fail('Choose the Shopee links .xlsx file.')
    with tempfile.TemporaryDirectory(prefix='firstwell_links_', ignore_cleanup_errors=True) as folder:
        path = Path(folder) / secure_filename(uploaded.filename)[:180]
        uploaded.save(path)
        try:
            rows, problems, extra = read_links_workbook(str(path), market)
        except ValueError as e:
            return fail(str(e))
        except Exception:
            current_app.logger.exception('Could not read links workbook')
            return fail('Could not read this Excel file.')
    if problems:
        return fail('Fix these rows first: ' + ' | '.join(problems[:8]) + (' …' if len(problems) > 8 else ''))
    if not rows:
        return fail('No rows have "Avixo ID to use" filled in.')
    return handler(rows, market, extra)


@bp.post('/preview')
def preview():
    def run(rows, market, extra):
        try:
            summary, *_ = plan(client(), rows, market, extra)
        except Exception:
            current_app.logger.exception('Links preview failed')
            return fail('Could not check the links against Supabase.', 503)
        return jsonify(ok=True, market=market, can_save=not summary['unknown_avixo_ids'], **summary)
    return _with_file(run)


@bp.post('/save')
def save():
    def run(rows, market, extra):
        db = client()
        try:
            summary, new, free, p_updates, v_updates, new_products = plan(db, rows, market, extra)
        except Exception:
            current_app.logger.exception('Links plan failed')
            return fail('Could not check the links against Supabase.', 503)
        if summary['unknown_avixo_ids']:
            return fail('These Avixo IDs are not in the product list: ' + ', '.join(summary['unknown_avixo_ids'][:15]))
        today = dt.datetime.now(KL).date().isoformat()
        try:
            if new_products:
                db.table('products').insert(new_products).execute()
            records = [dict(product_id=pid, observed_on=today, marketplace=market, shopee_item_id=item, shopee_variation_id=var)
                       for (item, var), pid in sorted(new.items())]
            db.table('product_channel_links').delete().eq('observed_on', today).eq('marketplace', market).execute()
            if records:
                db.table('product_channel_links').insert(records).execute()     # one request = all or nothing
            linked_items = {item for item, _ in new}
            flags = fetch_all(db, 'listing_flags', 'marketplace,shopee_item_id', {'marketplace': market}, 'shopee_item_id')
            stale = [f['shopee_item_id'] for f in flags if ident(f['shopee_item_id']) in linked_items]
            for start in range(0, len(stale), 200):
                db.table('listing_flags').delete().eq('marketplace', market).in_('shopee_item_id', stale[start:start + 200]).execute()
            if free:
                db.table('listing_flags').upsert([dict(marketplace=market, shopee_item_id=item, flag='free_item',
                                                       display_name=name[:120] or None)
                                                  for item, name in free.items()]).execute()
            for pid, ids in p_updates.items():
                for start in range(0, len(ids), 200):
                    db.table('shopee_sales_monthly').update(
                        dict(product_id=pid, mapping_status='matched' if pid else 'unmapped')).in_('id', ids[start:start + 200]).execute()
            for pid, ids in v_updates.items():
                for start in range(0, len(ids), 200):
                    db.table('shopee_variation_sales_monthly').update(
                        dict(product_id=pid, mapping_basis='Shopee links sheet' if pid else None)).in_('id', ids[start:start + 200]).execute()
        except Exception:
            current_app.logger.exception('Saving links failed')
            return fail('Saving stopped part-way. Upload the same file again to finish; nothing is duplicated.', 503)
        current_app.logger.warning('Shopee links saved by %s: %s', g.staff.get('email') if getattr(g, 'staff', None) else '?', summary)
        return jsonify(ok=True, market=market, saved_on=today,
                       message=f"Saved {summary['links_after']} links. {summary['sales_rows_rematched']} sales rows re-matched.", **summary)
    return _with_file(run)


def register_links_api(app):
    app.register_blueprint(bp)
