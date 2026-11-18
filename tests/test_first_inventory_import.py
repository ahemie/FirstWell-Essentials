"""Run: python3 tests/test_first_inventory_import.py  (fake Supabase client, no network).

The first Avixo inventory report into an empty database may be mid-month and creates the products.
Once any inventory exists, the normal month-end rule and the unknown-product stop apply again."""
import os, sys, datetime as dt
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('SUPABASE_URL', 'http://x'); os.environ.setdefault('SUPABASE_SERVICE_ROLE_KEY', 'x')
from backend import supabase_upload as su


class Q:
    def __init__(s, db, name): s.db = db; s.name = name; s.f = []; s.lim = None; s.rng = None
    def select(s, c): return s
    def order(s, c, desc=False): return s
    def eq(s, k, v): s.f.append((k, v)); return s
    def limit(s, n): s.lim = n; return s
    def range(s, a, b): s.rng = (a, b); return s
    def execute(s):
        rows = [r for r in s.db.get(s.name, []) if all(str(r.get(k)) == str(v) for k, v in s.f)]
        if s.rng: rows = rows[s.rng[0]:s.rng[1] + 1]
        if s.lim: rows = rows[:s.lim]
        return type('R', (), {'data': rows})


class DB:
    def __init__(s, data): s.data = data
    def table(s, name): return Q(s.data, name)
    def get(s, name, default): return s.data.get(name, default)


def fake_read_inventory(path):
    products = [dict(id='A1', name='Vitamin C', cat='Supplement', unit='Box', latest_cost=10, price=20, summary_balance=5),
                dict(id='A2', name='Zinc', cat=None, unit='Bottle', latest_cost=8, price=15, summary_balance=2)]
    batches = {'Vitamin C': [dict(expiry=dt.date(2027, 5, 1), qty=3, value_cost=30, value_retail=60),
                             dict(expiry=dt.date(2027, 8, 1), qty=2, value_cost=20, value_retail=40)],
               'Zinc': [dict(expiry=None, qty=2, value_cost=16, value_retail=30)]}
    return products, batches, dt.date(2026, 11, 18)


su.read_inventory = fake_read_inventory

# 1) Empty database, 18 Nov report -> accepted, products created, snapshot rows point at them.
tables, meta, warnings, _snap = su.prepare('x.xlsx', 'inventory', '2026-11', None, DB({}))
assert len(tables['products']) == 2, tables.keys()
pid = {p['avixo_id']: p['id'] for p in tables['products']}
assert {r['product_id'] for r in tables['inventory_snapshots']} == set(pid.values())
assert tables['inventory_snapshots'][0]['snapshot_date'] == '2026-11-18'
assert len(tables['inventory_batches']) == 3
assert [p['category'] for p in tables['products']] == ['Supplement', 'Uncategorised']
assert any('mid-month' in w for w in warnings) and any('2 products will be created' in w for w in warnings)
summary, conflicts = su.status_for(DB({}), tables)
assert not conflicts and summary['products']['new'] == 2, (summary, conflicts)
print('PASS: first inventory report, mid-month, creates products')

# 2) Wrong month for the first report is still refused.
try:
    su.prepare('x.xlsx', 'inventory', '2026-10', None, DB({})); raise SystemExit('FAIL: wrong month accepted')
except ValueError as e:
    assert 'inside the selected month' in str(e)
print('PASS: first report must be inside the selected month')

# 3) Inventory already exists -> normal rules are unchanged.
existing = DB({'inventory_snapshots': [dict(product_id='u1', snapshot_date='2026-10-31')],
               'products': [dict(id='u1', avixo_id='A1', name='Vitamin C')]})
try:
    su.prepare('x.xlsx', 'inventory', '2026-11', None, existing); raise SystemExit('FAIL: mid-month accepted')
except ValueError as e:
    assert 'month-end' in str(e)
print('PASS: later reports still need month-end')
