import datetime as dt
import unittest
from backend.stock_files_calc import calculate, detect, name_match, tokens, FileError


def avixo(prods, when='16/11/2026 03:38 PM'):
    head = [['Firststep'], [], ['Inventory Report'], ['Date', None, when], [], ['ID', 'Category', 'Name', 'Latest Cost Price', 'Wtd Avg Cost Price', 'Price', 'Balance', 'Stock Unit', 'Comments', 'Earliest Expiry']]
    summ = head + [[i, 'Medication', n, 1, 1, 1, bal, 'Box', cm, '01/01/2030'] for i, n, bal, cm in prods]
    me = [[], [], [], [], [], ['ID', 'Category', 'Name', 'a', 'b', 'c', 'Expiry Date', 'Stock Balance']] + \
         [[i, 'Medication', n, 1, 1, 1, e, q] for i, n, q, e in [(prods[0][0], prods[0][1], 5, '01/01/2029'), (prods[0][0], prods[0][1], 5, '01/01/2028')]]
    return {'Summary': summ, 'Multiple Expiry': me}


def shopee(cur, rows):
    h = ['Item ID', 'Product', 'Current Item Status', 'Variation ID', 'Variation Name', 'x', f'Sales (Placed Order) ({cur})', f'Sales (Paid Order) ({cur})', 'Units (Placed Order)', 'Units (Paid Order)']
    return {'Top Performing Products': [h] + [[a, b, 'Normal', c, d, '-', 0, 0, u, u] for a, b, c, d, u in rows]}


class Calc(unittest.TestCase):
    def test_remark_match_and_fefo(self):
        files = [('inventory', 'inv.xlsx', avixo([(1, 'Alpha cream 40ml', 10, 'SG|111|0; MY|222|0')])),
                 ('shopee_sg1', 'sg.xlsx', shopee('SGD', [('111', 'Whatever listing', '-', '-', 3)])),
                 ('shopee_my', 'my.xlsx', shopee('MYR', [('222', 'Other', '-', '-', 2)]))]
        r = calculate(files, dt.date(2026, 11, 16))
        row = r['rows'][0]
        self.assertEqual((row['before'], row['total'], row['after']), (10, 5, 5))
        self.assertEqual(row['sold']['shopee_sg1'], 3)
        self.assertEqual(row['expiry'], '01/01/2028 x5')
        self.assertEqual(row['check'], '')

    def test_variation_parent_not_double_counted(self):
        sheets = shopee('SGD', [('9', 'Gel', '-', '-', 3), ('9', 'Gel', '70', '15g', 1), ('9', 'Gel', '71', '60g', 2)])
        files = [('inventory', 'inv.xlsx', avixo([(1, 'Gel 15g', 10, 'SG|9|70'), (2, 'Gel 60g', 10, 'SG|9|71')])), ('shopee_sg1', 'sg.xlsx', sheets)]
        r = calculate(files, dt.date(2026, 11, 16))
        self.assertEqual({x['id']: x['total'] for x in r['rows']}, {1: 1, 2: 2})

    def test_name_match_picks_right_size_else_unmatched(self):
        pt = [({'id': 1, 'name': 'Gel 15g'}, tokens('Gel 15g')), ({'id': 2, 'name': 'Gel 60g'}, tokens('Gel 60g'))]
        self.assertEqual(name_match(pt, 'Gel 15g/60g | EXP', '15g')[0]['id'], 1)
        self.assertIsNone(name_match(pt, 'Totally different thing', '')[0])

    def test_unmatched_sale_is_reported_not_dropped(self):
        files = [('inventory', 'inv.xlsx', avixo([(1, 'Alpha cream 40ml', 10, '')])), ('shopee_sg1', 'sg.xlsx', shopee('SGD', [('555', 'Mystery item', '-', '-', 4)]))]
        r = calculate(files, dt.date(2026, 11, 16))
        self.assertEqual(r['rows'], [])
        self.assertEqual(r['unmatched'][0]['units'], 4)

    def test_sg1_and_sg2_are_separate_shops_with_own_remarks(self):
        inv = avixo([(1, 'Alpha cream 40ml', 10, 'SG1|111|0'), (2, 'Beta gel 15g', 10, 'SG2|111|0; SG|555|0')])
        files = [('inventory', 'inv.xlsx', inv), ('shopee_sg1', 'a_SG1.xlsx', shopee('SGD', [('555', 'x', '-', '-', 1), ('111', 'x', '-', '-', 2)])),
                 ('shopee_sg2', 'a_SG2.xlsx', shopee('SGD', [('111', 'x', '-', '-', 4)]))]
        r = calculate(files, dt.date(2026, 11, 16))
        by = {x['id']: x for x in r['rows']}
        self.assertEqual(by[1]['sold']['shopee_sg1'], 2)   # 111 in the SG1 shop
        self.assertEqual(by[2]['sold']['shopee_sg2'], 4)   # 111 in the SG2 shop is a different listing
        self.assertEqual(by[2]['sold']['shopee_sg1'], 1)   # plain SG| remark counts as SG1
        self.assertEqual([c['label'] for c in r['channels']], ['Shopee SG1', 'Shopee SG2'])

    def test_wrong_box_is_refused(self):
        inv = ('inventory', 'inv.xlsx', avixo([(1, 'Alpha', 10, '')]))
        with self.assertRaises(FileError):
            calculate([inv, ('shopee_my', 'x.xlsx', shopee('SGD', [('1', 'x', '-', '-', 1)]))])
        with self.assertRaises(FileError):
            calculate([inv, ('lazada', 'x.xlsx', shopee('MYR', [('1', 'x', '-', '-', 1)]))])

    def test_needs_inventory_and_known_files(self):
        with self.assertRaises(FileError):
            calculate([('shopee_sg1', 'sg.xlsx', shopee('SGD', [('1', 'x', '-', '-', 1)]))])
        self.assertIsNone(detect({'Sheet1': [['hello']]}))


class Remark(unittest.TestCase):
    def test_make_remark(self):
        from backend.stock_files_calc import make_remark
        self.assertEqual(make_remark({'shopee_sg1': 1, 'shopee_sg2': 1}, '2026-11-17'), '17112026 SG1 x1 SG2 x1')
        self.assertEqual(make_remark({'shopee_sg2': 3, 'tiktok': 0}, '2026-11-17'), '17112026 SG2 x3')
        self.assertEqual(make_remark({'lazada': 2}, None), 'LZD x2')

    def test_row_remark_and_date(self):
        files = [('inventory', 'inv.xlsx', avixo([(1, 'Alpha cream 40ml', 10, 'SG|111|0; SG2|333|0')])),
                 ('shopee_sg1', 'parentskudetail.20261117_20261117_SG1.xlsx', shopee('SGD', [('111', 'x', '-', '-', 1)])),
                 ('shopee_sg2', 'parentskudetail.20261117_20261117_SG2.xlsx', shopee('SGD', [('333', 'x', '-', '-', 1)]))]
        r = calculate(files, dt.date(2026, 11, 17))
        self.assertEqual(r['sales_date'], '2026-11-17')
        self.assertEqual(r['rows'][0]['remark'], '17112026 SG1 x1 SG2 x1')
        self.assertNotIn('app_stock', r['rows'][0])


class RemarkDates(unittest.TestCase):
    def test_each_platform_keeps_its_file_date(self):
        from backend.stock_files_calc import make_remark
        sold = {'shopee_sg1': 1, 'shopee_sg2': 1, 'lazada': 2}
        sd = {'shopee_sg1': '2026-11-17', 'shopee_sg2': '2026-11-17', 'lazada': '2026-11-16'}
        self.assertEqual(make_remark(sold, '2026-11-17', sd), '17112026 SG1 x1 SG2 x1; 16112026 LZD x2')
        self.assertEqual(make_remark(sold, '2026-11-18'), '18112026 SG1 x1 SG2 x1 LZD x2')
        self.assertEqual(make_remark({'shopee_sg1': 1}, '2026-11-17', sd), '17112026 SG1 x1')

    def test_calculate_returns_slot_dates(self):
        files = [('inventory', 'inv.xlsx', avixo([(1, 'Alpha cream 40ml', 10, 'SG|111|0; SG2|333|0')])),
                 ('shopee_sg1', 'parentskudetail.20261117_20261117_SG1.xlsx', shopee('SGD', [('111', 'x', '-', '-', 1)])),
                 ('shopee_sg2', 'parentskudetail.20261116_20261116_SG2.xlsx', shopee('SGD', [('333', 'x', '-', '-', 1)]))]
        r = calculate(files, dt.date(2026, 11, 17))
        self.assertEqual(r['slot_dates'], {'shopee_sg1': '2026-11-17', 'shopee_sg2': '2026-11-16'})
        self.assertEqual(r['rows'][0]['remark'], '17112026 SG1 x1; 16112026 SG2 x1')


if __name__ == '__main__':
    unittest.main()
