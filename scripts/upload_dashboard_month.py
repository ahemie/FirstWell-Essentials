"""Upload a processed month (data/YYYY-MM.json from process_month.py) into Supabase.

Default is a DRY RUN: it only reads and reports. Nothing is written without --apply.
An existing month is never overwritten unless you also pass --replace.

    py -m scripts.upload_dashboard_month data/2026-09.json            # preview
    py -m scripts.upload_dashboard_month data/2026-09.json --apply    # insert new month
    py -m scripts.upload_dashboard_month data/2026-09.json --apply --replace
"""
import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / '.env')
except ImportError:
    pass

TABLE = 'dashboard_months'
REQUIRED_META = ('month', 'label', 'today', 'fx')
REQUIRED_PRODUCT = ('id', 'n', 'c', 'q', 'val', 's')


def load_and_check(path):
    raw = Path(path).read_bytes()
    data = json.loads(raw.decode('utf-8'))
    problems = []
    meta, products = data.get('meta'), data.get('products')
    if not isinstance(meta, dict) or not isinstance(products, list):
        raise SystemExit('File must contain "meta" (object) and "products" (list).')
    for k in REQUIRED_META:
        if k not in meta:
            problems.append(f'meta is missing "{k}"')
    if not re.fullmatch(r'\d{4}-\d{2}', str(meta.get('month', ''))):
        problems.append('meta.month must look like 2026-09')
    # id is null for products that are only in the Movement report (SPEC flag: Not in Inventory Report)
    ids = [p.get('id') for p in products if p.get('id') is not None]
    if len(ids) != len(set(ids)):
        problems.append('duplicate product ids')
    for i, p in enumerate(products):
        for k in REQUIRED_PRODUCT:
            if k not in p:
                problems.append(f'product #{i} ({p.get("n")}) missing "{k}"')
                break
    if problems:
        raise SystemExit('Not uploaded. Problems:\n - ' + '\n - '.join(problems[:20]))
    return data, hashlib.sha256(raw).hexdigest()


def summary(data):
    p = data['products']
    return {
        'month': data['meta']['month'], 'label': data['meta']['label'],
        'products': len(p),
        'stock_units': round(sum(x.get('q') or 0 for x in p), 2),
        'stock_value_rm': round(sum(x.get('val') or 0 for x in p), 2),
        'clinic_units_sold': round(sum(x.get('s') or 0 for x in p), 2),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('file')
    ap.add_argument('--apply', action='store_true', help='write to Supabase (default: preview only)')
    ap.add_argument('--replace', action='store_true', help='allow replacing an existing month')
    args = ap.parse_args()

    data, sha = load_and_check(args.file)
    info = summary(data)
    print('File checks passed:', json.dumps(info))

    from backend.supabase_upload import client
    db = client()
    month = info['month']
    existing = db.table(TABLE).select('month_key,source_sha256,product_count,uploaded_at') \
                 .eq('month_key', month).execute().data
    if existing:
        e = existing[0]
        same = e['source_sha256'] == sha
        print(f'Month {month} already in Supabase ({e["product_count"]} products, uploaded {e["uploaded_at"]}).')
        print('Content is IDENTICAL to this file.' if same else 'Content DIFFERS from this file.')
        if same:
            print('Nothing to do.')
            return
        if not args.replace:
            raise SystemExit('Not changed. Use --replace only if you really mean to overwrite it.')
    else:
        print(f'Month {month} is new in Supabase.')

    if not args.apply:
        print('PREVIEW ONLY. Nothing was written. Add --apply to upload.')
        return

    row = {'month_key': month, 'label': data['meta']['label'], 'meta': data['meta'],
           'products': data['products'], 'product_count': len(data['products']),
           'source_sha256': sha, 'source_name': Path(args.file).name,
           'uploaded_at': 'now()'}
    row.pop('uploaded_at')  # let the database default set it
    db.table(TABLE).upsert(row, on_conflict='month_key').execute()

    back = db.table(TABLE).select('meta,products,product_count').eq('month_key', month).execute().data[0]
    ok = back['meta'] == data['meta'] and back['products'] == data['products']
    print('Uploaded. Read-back check:', 'EXACT MATCH' if ok else 'MISMATCH - investigate')
    if not ok:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
