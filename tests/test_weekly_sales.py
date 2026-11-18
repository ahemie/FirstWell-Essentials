"""Run: python tests/test_weekly_sales.py   (no database; uses an in-memory stand-in for Supabase)."""
import datetime as dt
import io
import itertools
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import openpyxl
from flask import Flask

import backend.weekly_sales_api as api


class Result:
    def __init__(self, data): self.data = data


class Query:
    def __init__(self, db, name):
        self.db, self.name, self.filters, self.mode, self.payload = db, name, [], 'select', None
        self.lo, self.hi, self.lim, self.sort = None, None, None, []

    def select(self, *_a): return self
    def eq(self, k, v): self.filters.append(lambda r: str(r.get(k)) == str(v)); return self
    def lte(self, k, v): self.filters.append(lambda r: str(r.get(k)) <= str(v)); return self
    def gte(self, k, v): self.filters.append(lambda r: str(r.get(k)) >= str(v)); return self
    def in_(self, k, vals): self.filters.append(lambda r: r.get(k) in vals); return self
    def order(self, k, **_): self.sort.append(k); return self
    def range(self, a, b): self.lo, self.hi = a, b; return self
    def limit(self, n): self.lim = n; return self
    def insert(self, rows): self.mode, self.payload = 'insert', rows; return self
    def delete(self): self.mode = 'delete'; return self

    def execute(self):
        table = self.db.tables.setdefault(self.name, [])
        if self.mode == 'insert':
            rows = self.payload if isinstance(self.payload, list) else [self.payload]
            out = []
            for r in rows:
                r = dict(r)
                r.setdefault('id', next(self.db.counter) if self.name == 'weekly_sales_rows' else f'imp-{next(self.db.counter)}')
                if self.db.fail_rows_after is not None and self.name == 'weekly_sales_rows':
                    raise RuntimeError('simulated failure while saving rows')
                if self.name == 'weekly_sales_imports':
                    for e in table:
                        if e['sha256'] == r['sha256']: raise RuntimeError('duplicate sha')
                table.append(r); out.append(r)
            return Result(out)
        rows = [r for r in table if all(f(r) for f in self.filters)]
        if self.mode == 'delete':
            for r in rows: table.remove(r)
            self.db.tables['weekly_sales_rows'] = [x for x in self.db.tables.get('weekly_sales_rows', []) if x['import_id'] in {i['id'] for i in self.db.tables.get('weekly_sales_imports', [])}]
            return Result(rows)
        for k in reversed(self.sort): rows = sorted(rows, key=lambda r: str(r.get(k)))
        if self.lo is not None: rows = rows[self.lo:self.hi + 1]
        if self.lim is not None: rows = rows[:self.lim]
        return Result(rows)


class FakeDB:
    def __init__(self, fail_rows_after=None):
        self.counter = itertools.count(1)
        self.fail_rows_after = fail_rows_after
        self.tables = {
            'products': [{'id': 'p-aero', 'avixo_id': '10', 'name': 'Aerochamber'}, {'id': 'p-gel', 'avixo_id': '11', 'name': 'Bruzzy gel'}],
            'product_channel_links': [
                {'id': 1, 'marketplace': 'MY', 'shopee_item_id': '1001', 'shopee_variation_id': '0', 'product_id': 'p-gel', 'observed_on': '2026-10-10'},
                {'id': 2, 'marketplace': 'SG', 'shopee_item_id': '2001', 'shopee_variation_id': '0', 'product_id': 'p-gel', 'observed_on': '2026-10-10'}],
        }
    def table(self, name): return Query(self, name)


def make_shopee(name, sg=False, rows=((1001, 'Bruzzy gel', 5, 100.0), (1002, 'Mystery', 2, 20.0))):
    wb = openpyxl.Workbook(); ws = wb.active; ws.title = 'Top Performing Products'
    cur = 'SGD' if sg else 'MYR'
    ws.append(['Item ID', 'Product', 'Variation ID', 'Units (Paid Order)' if sg else 'Units (Confirmed Order)', f'Sales (Paid Order) ({cur})' if sg else f'Sales (Confirmed Order) ({cur})'])
    for item, prod, u, s in rows:
        ws.append([item, prod, '-', u, s])
    p = Path(tempfile.mkdtemp()) / name; wb.save(p); return p


def make_movement(name, start, end, rows=(('Aerochamber', 4), ('Bruzzy gel', 3), ('Unknown thing', 1), ('Zero item', 0))):
    wb = openpyxl.Workbook(); ws = wb.active
    ws.append(['Report']); ws.append([]); ws.append([]); ws.append([])
    ws.append(['Date', None, f'From: {start} - To: {end}'])
    ws.append(['Category', 'Name', 'Cost Price', 'Stock Unit', 'Sold', 'Adjust', 'Closing Balance'])
    for n, sold in rows:
        ws.append(['Med', n, 1.0, 'Box', -sold, 0, 10])
    p = Path(tempfile.mkdtemp()) / name; wb.save(p); return p


def post(c, route, path, kind, start, end, sha=None):
    data = {'file': (io.BytesIO(path.read_bytes()), path.name), 'kind': kind, 'period_start': start, 'period_end': end}
    if sha: data['expected_sha256'] = sha
    r = c.post('/api/weekly-sales/' + route, data=data, content_type='multipart/form-data')
    return r.status_code, r.get_json()


def check(label, cond):
    print(('PASS ' if cond else 'FAIL ') + label)
    if not cond: check.failed = True
check.failed = False


def main():
    db = FakeDB()
    api.client = lambda: db
    app = Flask(__name__); api.register_weekly_sales_api(app); c = app.test_client()

    w1 = make_shopee('parentskudetail.20261005_20261011.xlsx')
    code, r = post(c, 'preview', w1, 'auto', '2026-10-05', '2026-10-11')
    check('week 1 MY preview ok, detected as Shopee MY, 2 rows, 1 unmapped', code == 200 and r['can_accept'] and r['metrics']['channel'] == 'shopee_my' and r['metrics']['rows'] == 2 and r['metrics']['unmapped_rows'] == 1)
    check('preview wrote nothing', not db.tables.get('weekly_sales_imports'))
    code, r2 = post(c, 'accept', w1, 'auto', '2026-10-05', '2026-10-11', r['sha256'])
    check('week 1 accepted', code == 200 and r2['inserted'] == 2 and len(db.tables['weekly_sales_imports']) == 1)

    code, r = post(c, 'preview', w1, 'auto', '2026-10-05', '2026-10-11')
    check('same file again -> already imported, cannot accept', code == 200 and r['already_imported'] and not r['can_accept'])
    code, r2 = post(c, 'accept', w1, 'auto', '2026-10-05', '2026-10-11', r['sha256'])
    check('accepting the same file adds nothing', code == 200 and r2['inserted'] == 0 and len(db.tables['weekly_sales_rows']) == 2)

    w2 = make_shopee('parentskudetail.20261012_20261018.xlsx', rows=((1001, 'Bruzzy gel', 7, 140.0),))
    code, r = post(c, 'preview', w2, 'auto', '2026-10-12', '2026-10-18')
    check('week 2 (next week) is fine', code == 200 and r['can_accept'])
    code, _ = post(c, 'accept', w2, 'auto', '2026-10-12', '2026-10-18', r['sha256'])
    check('week 2 accepted', code == 200 and len(db.tables['weekly_sales_imports']) == 2)

    ov = make_shopee('parentskudetail.20261010_20261016.xlsx', rows=((1001, 'Bruzzy gel', 9, 180.0),))
    code, r = post(c, 'preview', ov, 'auto', '2026-10-10', '2026-10-16')
    check('overlapping period is blocked', code == 200 and not r['can_accept'] and len(r['conflicts']) == 2)
    code, r2 = post(c, 'accept', ov, 'auto', '2026-10-10', '2026-10-16', r['sha256'])
    check('accept of an overlap is refused and saves nothing', code == 400 and len(db.tables['weekly_sales_imports']) == 2)

    mon = make_shopee('parentskudetail.20261005_20261011_sg.xlsx', sg=True, rows=((2001, 'Gel SG', 4, 60.0),))
    code, r = post(c, 'preview', mon, 'auto', '2026-10-06', '2026-10-11')
    check('dates that disagree with the file name are rejected', code == 400 and 'file name says' in r['error'])
    code, r = post(c, 'preview', mon, 'auto', '2026-10-05', '2026-10-11')
    check('SG detected, SGD, own channel (no clash with MY same dates)', code == 200 and r['can_accept'] and r['metrics']['currency'] == 'SGD')
    code, _ = post(c, 'accept', mon, 'auto', '2026-10-05', '2026-10-11', r['sha256'])

    mv = make_movement('Inventory_Movement_Report_wk1.xlsx', '05/10/2026', '11/10/2026')
    code, r = post(c, 'preview', mv, 'auto', '2026-10-05', '2026-10-11')
    check('clinic movement: zero rows skipped, units only, 3 rows', code == 200 and r['metrics']['channel'] == 'clinic' and r['metrics']['rows'] == 3 and r['metrics']['revenue'] is None)
    code, _ = post(c, 'accept', mv, 'auto', '2026-10-05', '2026-10-11', r['sha256'])
    code, r = post(c, 'preview', mv, 'auto', '2026-10-06', '2026-10-11')
    check('movement workbook period must equal entered dates', code == 400 and 'workbook period' in r['error'])

    code, r = post(c, 'preview', w1, 'auto', '2026-10-05', '2026-12-31')
    check('future / over-long period rejected', code == 400)
    inv = openpyxl.Workbook(); inv.active.title = 'Summary'; inv.create_sheet('Multiple Expiry')
    p = Path(tempfile.mkdtemp()) / 'Inventory_Report.xlsx'; inv.save(p)
    code, r = post(c, 'preview', p, 'auto', '2026-10-05', '2026-10-11')
    check('an Avixo inventory report is refused', code == 400 and 'only Shopee MY sales' in r['error'])

    code, s = c.get('/api/weekly-sales/summary?from=2026-10-05&to=2026-10-25').status_code, c.get('/api/weekly-sales/summary?from=2026-10-05&to=2026-10-25').get_json()
    tot = {t['channel']: t for t in s['totals']}
    check('range totals: MY = 5+7 units, 100+140 MYR', tot['shopee_my']['units'] == 14 and tot['shopee_my']['revenue'] == 260.0 and tot['shopee_my']['currency'] == 'MYR')
    check('SG kept in SGD, clinic units only (8)', tot['shopee_sg']['revenue'] == 60.0 and tot['shopee_sg']['currency'] == 'SGD' and tot['clinic']['units'] == 8 and tot['clinic']['revenue'] is None)
    check('gap reported for MY: 19 Oct to 25 Oct missing', s['gaps']['shopee_my'] == [['2026-10-19', '2026-10-25']])
    check('top products listed', s['top_products']['shopee_my'][0]['name'] == 'Bruzzy gel' and s['top_products']['shopee_my'][0]['units'] == 12)
    s2 = c.get('/api/weekly-sales/summary?from=2026-10-08&to=2026-10-25').get_json()
    check('an upload straddling the range edge is not counted and is mentioned', all(w['period_start'] != '2026-10-05' for w in s2['weeks']) and any('overlap the range edges' in n for n in s2['notes']))

    db2 = FakeDB(fail_rows_after=0); api.client = lambda: db2
    code, r = post(c, 'preview', w1, 'auto', '2026-10-05', '2026-10-11')
    code, r2 = post(c, 'accept', w1, 'auto', '2026-10-05', '2026-10-11', r['sha256'])
    check('a failure while saving rolls back (no half-saved import left)', code == 503 and not db2.tables.get('weekly_sales_imports'))
    print('\nALL PASSED' if not check.failed else '\nSOME FAILED'); sys.exit(1 if check.failed else 0)


if __name__ == '__main__':
    main()
