"""Run: python3 tests/test_trends.py  (no database access)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('SUPABASE_URL', 'http://x'); os.environ.setdefault('SUPABASE_SERVICE_ROLE_KEY', 'x')
from backend.monthly_data_api import build_trends
from backend.bi_api import shopee_listing_catalogue

products = [{'id': 1, 'avixo_id': '237'}, {'id': 2, 'avixo_id': '300'}]
summary = [{'report_month': m, 'channel': c} for m in ('2026-05-01', '2026-06-01')
           for c in ('Clinic', 'Shopee MY', 'Shopee SG')] + [{'report_month': '2026-07-01', 'channel': 'Shopee MY'}]
clinic = [{'report_month': '2026-05-01', 'product_id': 1, 'units_sold': '4', 'estimated_revenue_rm': '64.00'}]
sales = [{'report_month': '2026-05-01', 'marketplace': 'MY', 'product_id': 1, 'units_sold': 2, 'sales_amount': '30.5'},
         {'report_month': '2026-05-01', 'marketplace': 'MY', 'product_id': 1, 'units_sold': 1, 'sales_amount': '10'},
         {'report_month': '2026-06-01', 'marketplace': 'SG', 'product_id': 1, 'units_sold': 3, 'sales_amount': '18.07'}]
t = build_trends(summary, clinic, sales, products)
assert t['meta']['months'] == ['2026-05', '2026-06', '2026-07']
h = t['products']['237']
assert h['2026-05']['my'] == {'units': 3.0, 'revenue': 40.5}
assert h['2026-05']['clinic'] == {'units': 4.0, 'revenue': 64.0}
assert h['2026-06']['my'] == {'units': 0.0, 'revenue': 0.0}          # reported, nothing sold -> 0
assert h['2026-06']['sg'] == {'units': 3.0, 'revenue': 18.07}
assert h['2026-07']['clinic'] == {'units': None, 'revenue': None}    # no report -> gap, not zero
assert t['products']['300']['2026-05']['sg']['units'] == 0.0

links = [{'product_id': 1, 'marketplace': 'MY', 'shopee_item_id': 11}, {'product_id': 1, 'marketplace': 'MY', 'shopee_item_id': 12},
         {'product_id': 2, 'marketplace': 'MY', 'shopee_item_id': 21}]
prices = [{'marketplace': 'MY', 'snapshot_date': '2026-10-10', 'shopee_item_id': 11},
          {'marketplace': 'MY', 'snapshot_date': '2026-10-10', 'shopee_item_id': 99},
          {'marketplace': 'MY', 'snapshot_date': '2026-09-01', 'shopee_item_id': 55}]
names = {1: {'avixo_id': '237', 'name': 'Alpha'}, 2: {'avixo_id': '300', 'name': 'Beta'}}
cat = shopee_listing_catalogue(links, prices, names)
assert [x['key'] for x in cat['MY']] == ['p:237', 'p:300'], cat['MY']   # unlinked, unflagged listing is left out
assert cat['SG'] == []
flags = [{'marketplace': 'MY', 'shopee_item_id': '99', 'flag': 'free_item', 'display_name': 'Free gift'}]
cat2 = shopee_listing_catalogue(links, prices, names, flags)
free = [x for x in cat2['MY'] if x['key'] == 'u:99'][0]
assert free['name'] == 'Free gift' and free['flag'] == 'free_item' and free['mapped'] is False, free
print('PASS: trends + listing catalogue')
