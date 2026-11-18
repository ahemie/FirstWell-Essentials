import os
import unittest

os.environ.setdefault('FLASK_SECRET_KEY', 'k' * 40)
from backend import scrap_api as app
from backend.scrap_lib.keyword_scrape import clean_keyword, is_relevant, parse_listing_url, summarize


class KeywordHelperTests(unittest.TestCase):
    def test_clean_keyword(self):
        self.assertEqual(clean_keyword('  orac   kids  '), 'orac kids')
        self.assertEqual(clean_keyword('a'), '')
        self.assertEqual(clean_keyword(None), '')
        self.assertEqual(len(clean_keyword('x' * 500)), 120)

    def test_urls_are_checked_per_market(self):
        my = 'https://shopee.com.my/Orac-Kids-i.994773440.25500645266'
        sg = 'https://shopee.sg/Orac-Kids-i.123.456'
        self.assertEqual(parse_listing_url(my, 'MY'), ('994773440', '25500645266'))
        self.assertEqual(parse_listing_url(sg, 'SG'), ('123', '456'))
        self.assertEqual(parse_listing_url(sg, 'MY'), (None, None))
        self.assertEqual(parse_listing_url(my, 'SG'), (None, None))
        self.assertEqual(parse_listing_url('http://shopee.sg/x-i.1.2', 'SG'), (None, None))
        self.assertEqual(parse_listing_url('https://evil.example/shopee.sg/x-i.1.2', 'SG'), (None, None))
        self.assertEqual(parse_listing_url('https://shopee.sg/product/12/34', 'SG'), ('12', '34'))
        self.assertEqual(parse_listing_url(None, 'SG'), (None, None))
        self.assertEqual(parse_listing_url(sg, 'XX'), (None, None))

    def test_relevance(self):
        self.assertTrue(is_relevant('ORAC Kids Immune Booster 5g x 6 Sachets', 'orac kids immune booster'))
        self.assertTrue(is_relevant('ORAC Kids Immune Booster 5g x 6 Sachets', 'orac'))
        self.assertFalse(is_relevant('Redoxon Vitamin C 1000mg', 'orac kids immune booster'))
        # a stated pack must match
        self.assertTrue(is_relevant('ORAC Kids Immune Booster 5g x 6', 'orac kids immune booster 5g x 6'))
        self.assertFalse(is_relevant('ORAC Kids Immune Booster 5g x 30', 'orac kids immune booster 5g x 6'))
        self.assertFalse(is_relevant('Nan Optipro 800g', 'nan optipro 400g'))
        self.assertTrue(is_relevant('Nan Optipro 400g', 'nan optipro 400g'))

    def test_summary_ignores_excluded_and_own(self):
        rows = [{'price': 10, 'included': True}, {'price': 20, 'included': True}, {'price': 40, 'included': True},
                {'price': 1, 'included': False}, {'price': 2, 'included': True, 'is_own': True}]
        s = summarize(rows)
        self.assertEqual((s['included_count'], s['lowest'], s['highest'], s['median']), (3, 10.0, 40.0, 20.0))
        self.assertAlmostEqual(s['average'], 23.33, places=2)
        self.assertEqual(summarize([])['lowest'], None)


class NormaliseTests(unittest.TestCase):
    def test_sg_item(self):
        item = {'name': 'Orac Kids Immune Booster 5g x 6', 'url': 'https://shopee.sg/x-i.111.222', 'price': 'S$12.90',
                'rating': 4.9, 'sold_count': '1.2k', 'currency': 'SGD'}
        row = app.normalise_result(item, 'SG', 'orac kids immune booster', [], [])
        self.assertEqual((row['shop_id'], row['item_id'], row['price']), ('111', '222', 12.9))
        self.assertEqual((row['sold_count'], row['relevant'], row['included'], row['is_own']), (1200, True, True, False))

    def test_own_shop_is_never_included(self):
        item = {'name': 'Orac Kids Immune Booster', 'url': 'https://shopee.com.my/x-i.994773440.5', 'price': 30}
        row = app.normalise_result(item, 'MY', 'orac kids', [], [])
        self.assertTrue(row['is_own'])
        self.assertFalse(row['included'])

    def test_unusable_items_are_skipped(self):
        self.assertIsNone(app.normalise_result({'name': 'x', 'url': 'https://shopee.sg/x-i.1.2'}, 'SG', 'x y', [], []))   # no price
        self.assertIsNone(app.normalise_result({'name': 'x', 'price': 5, 'url': 'https://shopee.sg/nope'}, 'SG', 'x y', [], []))
        self.assertIsNone(app.normalise_result('text', 'SG', 'x y', [], []))


if __name__ == '__main__':
    unittest.main()
