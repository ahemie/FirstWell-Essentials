"""FirstWell Essentials: preview/import Shopee variation-level monthly performance.

Usage (inside FirstWell_Essentials_Supabase):
    py import_shopee_variations.py
    py import_shopee_variations.py --apply

Requires existing process_month.py, .env and six Excel files in source_reports/.
Does NOT modify shopee_sales_monthly (parent-level source totals).
"""
import argparse
import hashlib
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client
from process_month import read_shopee_perf

BASE = Path(__file__).resolve().parent.parent
REPORT_DIR = BASE / 'source_reports'
MAPPING_SNAPSHOT = '2026-10-01'
FILES = {
    ('MY', '2026-07'): 'parentskudetail_July_MY.xlsx',
    ('MY', '2026-08'): 'parentskudetail_August_MY.xlsx',
    ('MY', '2026-09'): 'parentskudetail_September_MY.xlsx',
    ('SG', '2026-07'): 'parentskudetail_July_SG.xlsx',
    ('SG', '2026-08'): 'parentskudetail_August_SG.xlsx',
    ('SG', '2026-09'): 'parentskudetail_September_SG.xlsx',
}
COLUMNS = {
    'MY': ('Units (Confirmed Order)', 'Sales (Confirmed Order) (MYR)', 'MYR'),
    'SG': ('Units (Paid Order)', 'Sales (Paid Order) (SGD)', 'SGD'),
}


def ident(value):
    text = str(value).strip()
    if text.endswith('.0') and text[:-2].isdigit():
        return text[:-2]
    return text


def fetch_all(db, table, columns, **filters):
    result = []
    offset = 0
    while True:
        q = db.table(table).select(columns).order('id')
        for key, value in filters.items():
            q = q.eq(key, value)
        batch = q.range(offset, offset + 499).execute().data or []
        result.extend(batch)
        if len(batch) < 500:
            return result
        offset += 500


def read_reports():
    output = []
    for (market, month), filename in FILES.items():
        path = REPORT_DIR / filename
        if not path.is_file():
            raise FileNotFoundError(f'Missing report: {path}')
        units_col, revenue_col, currency = COLUMNS[market]
        parents, variations = read_shopee_perf(str(path), units_col, revenue_col)
        variation_by_item = defaultdict(list)
        for (item, var), values in variations.items():
            item, var = ident(item), ident(var)
            if not item or not var or var in ('-', 'None', 'nan'):
                raise ValueError(f'Invalid variation ID in {filename}: {item}/{var}')
            variation_by_item[item].append((var, values))

        # Only variation rows are inserted. Parent rows remain exclusively
        # in shopee_sales_monthly for reporting/reconciliation.
        problems = []
        for item, parts in variation_by_item.items():
            parent = parents.get(item)
            if parent is None:
                problems.append(f'{item}: variation rows have no parent record')
                continue
            sum_units = sum(float(v.get('units') or 0) for _, v in parts)
            sum_sales = sum(float(v.get('sales') or 0) for _, v in parts)
            if abs(sum_units - float(parent.get('units') or 0)) > .01 or abs(sum_sales - float(parent.get('sales') or 0)) > .05:
                problems.append(f'{item}: parent={parent}; variations={sum_units}, {sum_sales:.2f}')

        fingerprint = hashlib.sha256(path.read_bytes()).hexdigest()
        rows = []
        for (item, var), values in variations.items():
            rows.append({
                'report_month': month + '-01',
                'marketplace': market,
                'shopee_item_id': ident(item),
                'shopee_variation_id': ident(var),
                'units_sold': float(values.get('units') or 0),
                'sales_amount': round(float(values.get('sales') or 0), 2),
                'currency': currency,
                'product_id': None,
                'mapping_basis': None,
                'source_filename': filename,
                'source_sha256': fingerprint,
            })
        output.append((market, month, rows, problems))
    return output


def get_links(db):
    links = fetch_all(db, 'product_channel_links',
                      'id,product_id,observed_on,marketplace,shopee_item_id,shopee_variation_id')
    owner = defaultdict(set)
    for link in links:
        if link['observed_on'] != MAPPING_SNAPSHOT:
            continue
        if ident(link['shopee_variation_id']) == '0':
            continue
        key = (link['marketplace'], ident(link['shopee_item_id']), ident(link['shopee_variation_id']))
        owner[key].add(link['product_id'])
    return {key: next(iter(value)) for key, value in owner.items() if len(value) == 1}, {key for key, value in owner.items() if len(value) > 1}


def prepare(db, months):
    owner, conflicts = get_links(db)
    existing = fetch_all(db, 'shopee_variation_sales_monthly',
                         'id,report_month,marketplace,shopee_item_id,shopee_variation_id,units_sold,sales_amount,currency,product_id,source_sha256')
    by_key = {
        (r['marketplace'], r['report_month'], ident(r['shopee_item_id']), ident(r['shopee_variation_id'])): r
        for r in existing
    }
    pending, errors = [], []
    seen = set()
    stats = Counter()
    for market, month, rows, problems in months:
        if problems:
            errors.extend(f'{market} {month}: {issue}' for issue in problems)
        for row in rows:
            link_key = (market, row['shopee_item_id'], row['shopee_variation_id'])
            if link_key in conflicts:
                errors.append(f'Conflicting Avixo links for {link_key}')
                continue
            row['product_id'] = owner.get(link_key)
            if row['product_id']:
                row['mapping_basis'] = 'provisional:inventory_snapshot_2026-10-01'
                stats['matched_variation_rows'] += 1
            else:
                stats['unmatched_variation_rows'] += 1
            key = (market, row['report_month'], row['shopee_item_id'], row['shopee_variation_id'])
            if key in seen:
                errors.append(f'Duplicate variation record: {key}')
                continue
            seen.add(key)
            old = by_key.get(key)
            if old:
                # Never silently overwrite a previous month/version or mapping.
                if (str(old['source_sha256']) != row['source_sha256'] or
                    abs(float(old['units_sold']) - row['units_sold']) > .001 or
                    abs(float(old['sales_amount']) - row['sales_amount']) > .01 or
                    old['product_id'] != row['product_id']):
                    errors.append(f'Existing row differs; manual review required: {key}')
                else:
                    stats['already_saved'] += 1
            else:
                pending.append(row)
    return pending, stats, errors


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true', help='Insert verified variation rows')
    args = parser.parse_args()
    load_dotenv(BASE / '.env')
    print('\nFIRSTSTEP SHOPEE VARIATION SALES')
    print('----------------------------------')
    months = read_reports()
    for market, month, rows, problems in months:
        print(f'{market} {month}: {len(rows)} variation rows; reconciliation issues: {len(problems)}')
    url = os.getenv('SUPABASE_URL')
    key = os.getenv('SUPABASE_SERVICE_ROLE_KEY')
    if not url or not key:
        raise RuntimeError('Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY in .env')
    db = create_client(url, key)
    pending, stats, errors = prepare(db, months)
    print('Matched variation rows:', stats['matched_variation_rows'])
    print('Unmatched variation rows:', stats['unmatched_variation_rows'])
    print('Already saved:', stats['already_saved'])
    print('New variation rows:', len(pending))
    print('Parent sales totals: unchanged')
    print('Mapping basis: October 1 snapshot (provisional for earlier months)')
    if errors:
        print('\nBLOCKED: found', len(errors), 'issues. First 12:')
        for error in errors[:12]:
            print('-', error)
        raise RuntimeError('No changes made; review the issues above')
    if not args.apply:
        print('\nPREVIEW ONLY — no Supabase changes.')
        print('After review: py import_shopee_variations.py --apply')
        return
    for start in range(0, len(pending), 100):
        batch = pending[start:start + 100]
        db.table('shopee_variation_sales_monthly').insert(batch).execute()
        print(f'Saved {min(start + 100, len(pending))} / {len(pending)}')
    print('\nSUCCESS — only variation records were added.')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('\nSTOP:', exc)
        sys.exit(1)
