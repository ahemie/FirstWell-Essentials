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
                 ('shopee_sg', 'sg.xlsx', shopee('SGD', [('111', 'Whatever listing', '-', '-', 3)])),
                 ('shopee_my', 'my.xlsx', shopee('MYR', [('222', 'Other', '-', '-', 2)]))]
        r = calculate(files, dt.date(2026, 11, 16))
        row = r['rows'][0]
        self.assertEqual((row['before'], row['total'], row['after']), (10, 5, 5))
        self.assertEqual(row['sold']['shopee_sg'], 3)
        self.assertEqual(row['expiry'], '01/01/2028 x5')
        self.assertEqual(row['check'], '')

    def test_variation_parent_not_double_counted(self):
        sheets = shopee('SGD', [('9', 'Gel', '-', '-', 3), ('9', 'Gel', '70', '15g', 1), ('9', 'Gel', '71', '60g', 2)])
        files = [('inventory', 'inv.xlsx', avixo([(1, 'Gel 15g', 10, 'SG|9|70'), (2, 'Gel 60g', 10, 'SG|9|71')])), ('shopee_sg', 'sg.xlsx', sheets)]
        r = calculate(files, dt.date(2026, 11, 16))
        self.assertEqual({x['id']: x['total'] for x in r['rows']}, {1: 1, 2: 2})

    def test_name_match_picks_right_size_else_unmatched(self):
        pt = [({'id': 1, 'name': 'Gel 15g'}, tokens('Gel 15g')), ({'id': 2, 'name': 'Gel 60g'}, tokens('Gel 60g'))]
        self.assertEqual(name_match(pt, 'Gel 15g/60g | EXP', '15g')[0]['id'], 1)
        self.assertIsNone(name_match(pt, 'Totally different thing', '')[0])

    def test_unmatched_sale_is_reported_not_dropped(self):
        files = [('inventory', 'inv.xlsx', avixo([(1, 'Alpha cream 40ml', 10, '')])), ('shopee_sg', 'sg.xlsx', shopee('SGD', [('555', 'Mystery item', '-', '-', 4)]))]
        r = calculate(files, dt.date(2026, 11, 16))
        self.assertEqual(r['rows'], [])
        self.assertEqual(r['unmatched'][0]['units'], 4)

    def test_saved_pairing_matches_listing_and_candidates_are_offered(self):
        inv = avixo([(1, 'Alpha cream 40ml', 10, ''), (2, 'Beta gel 15g', 10, '')])
        sheets = shopee('MYR', [('777', 'Totally different wording', '-', '-', 4)])
        files = [('inventory', 'inv.xlsx', inv), ('shopee_my', 'my.xlsx', sheets)]
        r = calculate(files, dt.date(2026, 11, 16))
        u = r['unmatched'][0]
        self.assertEqual((u['market'], u['item'], u['var_key']), ('MY', '777', '0'))
        self.assertEqual({p['id'] for p in r['products']}, {1, 2})
        r2 = calculate(files, dt.date(2026, 11, 16), aliases={('MY', '777', '0'): '2'})
        self.assertEqual(r2['unmatched'], [])
        self.assertEqual(r2['rows'][0]['id'], 2)
        self.assertEqual(r2['rows'][0]['sold']['shopee_my'], 4)
        self.assertEqual(r2['paired'][0]['avixo_name'], 'Beta gel 15g')
        # a pairing to a product that is not in this Avixo report is ignored, not a crash
        r3 = calculate(files, dt.date(2026, 11, 16), aliases={('MY', '777', '0'): '99'})
        self.assertEqual(len(r3['unmatched']), 1)

    def test_candidates_rank_closest_name_first(self):
        pt = [({'id': 1, 'name': 'Alpha cream 40ml'}, tokens('Alpha cream 40ml')), ({'id': 2, 'name': 'Beta gel 15g'}, tokens('Beta gel 15g'))]
        from backend.stock_files_calc import candidates
        c = candidates(pt, 'ALPHA Cream Original 40ml READY STOCK', '')
        self.assertEqual(c[0]['id'], 1)

    def test_one_sg_shop_and_old_sg1_sg2_remarks_count_as_sg(self):
        inv = avixo([(1, 'Alpha cream 40ml', 10, 'SG1|111|0'), (2, 'Beta gel 15g', 10, 'SG2|222|0; SG|555|0')])
        files = [('inventory', 'inv.xlsx', inv),
                 ('shopee_sg', 'a_SG.xlsx', shopee('SGD', [('555', 'x', '-', '-', 1), ('111', 'x', '-', '-', 2), ('222', 'x', '-', '-', 4)]))]
        r = calculate(files, dt.date(2026, 11, 16))
        by = {x['id']: x for x in r['rows']}
        self.assertEqual(by[1]['sold']['shopee_sg'], 2)
        self.assertEqual(by[2]['sold']['shopee_sg'], 5)
        self.assertEqual([c['label'] for c in r['channels']], ['Shopee SG'])

    def test_shopee_ph_file_is_refused(self):
        inv = ('inventory', 'inv.xlsx', avixo([(1, 'Alpha', 10, '')]))
        with self.assertRaisesRegex(FileError, 'Shopee PH'):
            calculate([inv, ('shopee_sg', 'a_PH.xlsx', shopee('PHP', [('1', 'x', '-', '-', 1)]))])
        self.assertEqual([c for c, _ in __import__('backend.stock_files_calc', fromlist=['x']).CHANNELS], ['shopee_my', 'shopee_sg', 'tiktok'])

    def test_lazada_file_is_refused(self):
        inv = ('inventory', 'inv.xlsx', avixo([(1, 'Alpha', 10, '')]))
        laz = {'Sheet1': [['Data Source: Lazada Business Advisor'], ['Product ID']]}
        with self.assertRaisesRegex(FileError, 'Lazada'):
            calculate([inv, ('shopee_my', 'lazada.xlsx', laz)])

    def test_shopee_file_in_the_wrong_box_goes_by_currency(self):
        inv = ('inventory', 'inv.xlsx', avixo([(1, 'Alpha', 10, 'SG|1|0; MY|2|0')]))
        r = calculate([inv, ('shopee_my', 'x_MY.xlsx', shopee('SGD', [('1', 'x', '-', '-', 1)])),
                       ('shopee_sg', 'x_SG.xlsx', shopee('MYR', [('2', 'x', '-', '-', 3)]))])
        self.assertEqual(r['rows'][0]['sold'], {'shopee_my': 3, 'shopee_sg': 1, 'tiktok': 0})
        self.assertTrue(any('counted as Shopee SG' in n for n in r['notes']))
        with self.assertRaises(FileError):     # a Shopee file in the TikTok box is still refused
            calculate([inv, ('tiktok', 'x.xlsx', shopee('MYR', [('2', 'x', '-', '-', 1)]))])

    def test_saved_shopee_links_match_after_remarks(self):
        inv = ('inventory', 'inv.xlsx', avixo([(7, 'Totally different name', 10, '')]))
        r = calculate([inv, ('shopee_my', 'a.xlsx', shopee('MYR', [('99', 'Listing title', '-', '-', 2)]))],
                      saved_links={('MY', '99', '0'): '7', ('MY', '98', '0'): 'FS-5'})
        self.assertEqual((r['rows'][0]['id'], r['rows'][0]['total'], r['rows'][0]['check']), (7, 2, ''))

    def test_saved_link_from_the_other_avixo_goes_by_name_not_id(self):
        # PJ Avixo: Ceravis is 1065. FirstStep Avixo: 1065 is something else and Ceravis is 501.
        inv = ('inventory', 'inv.xlsx', avixo([(1065, 'SMARTBuddy Iron Up 120G', 10, ''), (501, 'Ceravis Gentle Skin Cleanser 300ml', 10, ''),
                                               (938, 'Ivygard Ivy Leaf Drops 6s', 5, '')]))
        r = calculate([inv, ('shopee_my', 'a.xlsx', shopee('MYR', [('11', 'Listing A', '-', '-', 1), ('22', 'Listing B', '-', '-', 2)]))],
                      saved_links={('MY', '11', '0'): ('1065', 'Ceravis Gentle Skin Cleanser 300ml'),
                                   ('MY', '22', '0'): ('FS-938', 'Ivygard Ivy Leaf Drops 6s')})
        self.assertEqual({x['id']: x['total'] for x in r['rows']}, {501: 1, 938: 2})

    def test_needs_inventory_and_known_files(self):
        with self.assertRaises(FileError):
            calculate([('shopee_sg', 'sg.xlsx', shopee('SGD', [('1', 'x', '-', '-', 1)]))])
        self.assertIsNone(detect({'Sheet1': [['hello']]}))


class Remark(unittest.TestCase):
    def test_make_remark(self):
        from backend.stock_files_calc import make_remark
        self.assertEqual(make_remark({'shopee_my': 1, 'shopee_sg': 1}, '2026-11-17'), '17112026 MY x1 SG x1')
        self.assertEqual(make_remark({'shopee_sg': 3, 'tiktok': 0}, '2026-11-17'), '17112026 SG x3')
        self.assertEqual(make_remark({'tiktok': 2}, None), 'TT x2')

    def test_row_remark_and_date(self):
        files = [('inventory', 'inv.xlsx', avixo([(1, 'Alpha cream 40ml', 10, 'SG|111|0; MY|333|0')])),
                 ('shopee_sg', 'parentskudetail.20261117_20261117_SG.xlsx', shopee('SGD', [('111', 'x', '-', '-', 1)])),
                 ('shopee_my', 'parentskudetail.20261117_20261117_MY.xlsx', shopee('MYR', [('333', 'x', '-', '-', 1)]))]
        r = calculate(files, dt.date(2026, 11, 17))
        self.assertEqual(r['sales_date'], '2026-11-17')
        self.assertEqual(r['rows'][0]['remark'], '17112026 MY x1 SG x1')
        self.assertNotIn('app_stock', r['rows'][0])


class RemarkDates(unittest.TestCase):
    def test_each_platform_keeps_its_file_date(self):
        from backend.stock_files_calc import make_remark
        sold = {'shopee_my': 1, 'shopee_sg': 1, 'tiktok': 2}
        sd = {'shopee_my': '2026-11-17', 'shopee_sg': '2026-11-17', 'tiktok': '2026-11-16'}
        self.assertEqual(make_remark(sold, '2026-11-17', sd), '17112026 MY x1 SG x1; 16112026 TT x2')
        self.assertEqual(make_remark(sold, '2026-11-18'), '18112026 MY x1 SG x1 TT x2')

    def test_calculate_returns_slot_dates(self):
        files = [('inventory', 'inv.xlsx', avixo([(1, 'Alpha cream 40ml', 10, 'SG|111|0; MY|333|0')])),
                 ('shopee_sg', 'parentskudetail.20261117_20261117_SG.xlsx', shopee('SGD', [('111', 'x', '-', '-', 1)])),
                 ('shopee_my', 'parentskudetail.20261116_20261116_MY.xlsx', shopee('MYR', [('333', 'x', '-', '-', 1)]))]
        r = calculate(files, dt.date(2026, 11, 17))
        self.assertEqual(r['slot_dates'], {'shopee_sg': '2026-11-17', 'shopee_my': '2026-11-16'})
        self.assertEqual(r['rows'][0]['remark'], '16112026 MY x1; 17112026 SG x1')


if __name__ == '__main__':
    unittest.main()
