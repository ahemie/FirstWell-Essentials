"""Run: python3 tests/test_links_api.py  (in-memory fake Supabase, no network)."""
import io, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('SUPABASE_URL', 'http://x'); os.environ.setdefault('SUPABASE_SERVICE_ROLE_KEY', 'x')
import openpyxl
from flask import Flask
from backend import links_api


class Q:
    def __init__(s, db, name): s.db, s.name, s.f, s.op, s.payload, s.rng = db, name, [], 'select', None, None
    def select(s, c): return s
    def order(s, c, desc=False): return s
    def range(s, a, b): s.rng = (a, b); return s
    def eq(s, k, v): s.f.append(lambda r, k=k, v=v: str(r.get(k)) == str(v)); return s
    def in_(s, k, vs): vs = {str(v) for v in vs}; s.f.append(lambda r, k=k: str(r.get(k)) in vs); return s
    def delete(s): s.op = 'delete'; return s
    def insert(s, p): s.op, s.payload = 'insert', p; return s
    def upsert(s, p): s.op, s.payload = 'upsert', p; return s
    def update(s, p): s.op, s.payload = 'update', p; return s
    def execute(s):
        rows = s.db.setdefault(s.name, [])
        hit = lambda r: all(f(r) for f in s.f)
        if s.op == 'insert': rows.extend(dict(x) for x in s.payload)
        elif s.op == 'upsert':
            for x in s.payload:
                rows[:] = [r for r in rows if not (r['marketplace'] == x['marketplace'] and r['shopee_item_id'] == x['shopee_item_id'])]
                rows.append(dict(x))
        elif s.op == 'delete': rows[:] = [r for r in rows if not hit(r)]
        elif s.op == 'update':
            for r in rows:
                if hit(r): r.update(s.payload)
        else:
            out = [r for r in rows if hit(r)]
            if s.rng: out = out[s.rng[0]:s.rng[1] + 1]
            return type('R', (), {'data': out})
        return type('R', (), {'data': None})


class DB:
    def __init__(s, data): s.data = data
    def table(s, name): return Q(s.data, name)


def sheet(rows, fs=()):
    wb = openpyxl.Workbook(); ws = wb.active; ws.title = 'Links'
    ws.append(['Marketplace', 'Shopee item ID', 'Variation ID', 'Shopee product name', 'Avixo ID to use'])
    for r in rows: ws.append(r)
    ps = wb.create_sheet('Avixo products'); ps.append(['Avixo ID', 'Product name', 'Category'])
    for r in fs: ps.append(r)
    b = io.BytesIO(); wb.save(b); b.seek(0); return b


data = {
    'products': [dict(id='u-vitc', avixo_id='10', name='Vit C'), dict(id='u-b15', avixo_id='20', name='Benzac 15g'),
                 dict(id='u-b60', avixo_id='21', name='Benzac 60g')],
    'product_channel_links': [dict(product_id='u-vitc', observed_on='2026-10-01', marketplace='MY', shopee_item_id='999', shopee_variation_id='0')],
    'shopee_sales_monthly': [dict(id=1, marketplace='MY', shopee_item_id='111', product_id=None, mapping_status='unmapped'),
                             dict(id=2, marketplace='MY', shopee_item_id='222', product_id=None, mapping_status='unmapped'),
                             dict(id=3, marketplace='MY', shopee_item_id='333', product_id=None, mapping_status='unmapped')],
    'shopee_variation_sales_monthly': [dict(id=7, marketplace='MY', shopee_item_id='222', shopee_variation_id='5', product_id=None),
                                       dict(id=8, marketplace='MY', shopee_item_id='222', shopee_variation_id='6', product_id=None),
                                       dict(id=9, marketplace='MY', shopee_item_id='111', shopee_variation_id='4', product_id=None)],
    'listing_flags': [],
}
links_api.client = lambda: DB(data)
app = Flask(__name__); links_api.register_links_api(app)
c = app.test_client()
good = [['MY', '111', '0', 'Vit C listing', '10'], ['MY', '222', '5', 'Benzac 15g', '20'], ['MY', '222', '6', 'Benzac 60g', 21],
        ['MY', '333', '0', 'Gift', 'free'], ['MY', '444', '0', 'skip me', None]]

r = c.post('/api/links/preview', data={'market': 'MY', 'file': (sheet(good), 'l.xlsx')}).get_json()
assert r['ok'] and r['can_save'] and r['rows_in_file'] == 4 and r['links_after'] == 4 and r['sales_rows_rematched'] == 4, r
assert len(data['product_channel_links']) == 1, 'preview must not write'
print('PASS: preview counts, nothing written')

r = c.post('/api/links/save', data={'market': 'MY', 'file': (sheet(good), 'l.xlsx')}).get_json()
assert r['ok'], r
newest = [x for x in data['product_channel_links'] if x['observed_on'] == r['saved_on']]
assert {(x['shopee_item_id'], x['shopee_variation_id'], x['product_id']) for x in newest} == {
    ('999', '0', 'u-vitc'), ('111', '0', 'u-vitc'), ('222', '5', 'u-b15'), ('222', '6', 'u-b60')}, newest
s = {x['id']: x for x in data['shopee_sales_monthly']}
v = {x['id']: x for x in data['shopee_variation_sales_monthly']}
assert s[1]['product_id'] == 'u-vitc' and s[1]['mapping_status'] == 'matched'
assert s[2]['product_id'] is None                       # per-variation listing: parent stays, variations carry it
assert v[7]['product_id'] == 'u-b15' and v[8]['product_id'] == 'u-b60' and v[9]['product_id'] == 'u-vitc'
assert data['listing_flags'] == [dict(marketplace='MY', shopee_item_id='333', flag='free_item', display_name='Gift')]
print('PASS: save writes a full new link set, re-matches parent + variation sales, flags FREE')

r2 = c.post('/api/links/save', data={'market': 'MY', 'file': (sheet(good), 'l.xlsx')}).get_json()
assert r2['ok'] and r2['sales_rows_rematched'] == 0
assert len([x for x in data['product_channel_links'] if x['observed_on'] == r['saved_on']]) == 4
print('PASS: saving the same file twice changes nothing and does not duplicate')

bad = c.post('/api/links/preview', data={'market': 'MY', 'file': (sheet([['MY', '555', '0', 'x', '77']]), 'l.xlsx')}).get_json()
assert bad['can_save'] is False and bad['unknown_avixo_ids'] == ['77']
clash = c.post('/api/links/preview', data={'market': 'MY', 'file': (sheet([['MY', '555', '0', 'x', '10'], ['MY', '555', '0', 'x', '20']]), 'l.xlsx')})
assert clash.status_code == 400 and 'two different' in clash.get_json()['error']
print('PASS: unknown Avixo IDs and conflicting rows are refused')

fsr = c.post('/api/links/save', data={'market': 'MY', 'file': (sheet([['MY', '666', '0', 'Ivygard', 'FS-938']],
             [['FS-938', "Ivygard Ivy Leaf Drops 6's", 'FirstStep stock']]), 'l.xlsx')}).get_json()
assert fsr['ok'] and fsr['firststep_products_added'] == 1, fsr
made = [p for p in data['products'] if p['avixo_id'] == 'FS-938'][0]
assert made['category'] == 'FirstStep stock' and any(x['shopee_item_id'] == '666' and x['product_id'] == made['id']
                                                      for x in data['product_channel_links'])
again = c.post('/api/links/preview', data={'market': 'MY', 'file': (sheet([['MY', '666', '0', 'Ivygard', 'FS-938']],
               [['FS-938', "Ivygard Ivy Leaf Drops 6's", 'FirstStep stock']]), 'l.xlsx')}).get_json()
assert again['firststep_products_added'] == 0
missing = c.post('/api/links/preview', data={'market': 'MY', 'file': (sheet([['MY', '667', '0', 'x', 'FS-1']]), 'l.xlsx')}).get_json()
assert missing['unknown_avixo_ids'] == ['FS-1']
print('PASS: FirstStep Avixo products (FS-) are created once and linked')
