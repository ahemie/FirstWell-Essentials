import os
import unittest

os.environ.setdefault('FLASK_SECRET_KEY', 'k' * 40)
from backend import scrap_api as app


class ScrapeStatsTests(unittest.TestCase):
    def test_count_parsing(self):
        for raw, want in [(1234, 1234), ('1,234', 1234), ('1.2k', 1200), ('10k+', 10000), ('2.5m', 2500000),
                          ('300 sold', 300), (None, None), ('n/a', None), (-5, None), (True, None)]:
            self.assertEqual(app._count(raw), want, raw)

    def test_item_stats_from_actor_fields(self):
        stats = app._item_stats({'rating': 4.87, 'rating_count': '1.2k', 'sold_count': 530, 'original_price': 'RM 25.00',
                                 'discount_pct': 20, 'location': 'Selangor', 'price': 20})
        self.assertEqual(stats, {'rating': 4.87, 'rating_count': 1200, 'sold_count': 530, 'original_price': 25.0,
                                 'discount_pct': 20.0, 'location': 'Selangor'})

    def test_missing_values_are_left_out(self):
        self.assertEqual(app._item_stats({'rating': 5, 'rating_count': None, 'sold_count': None, 'location': None}), {'rating': 5.0})
        self.assertEqual(app._item_stats({'rating': 9}), {})  # out-of-range rating is ignored


if __name__ == '__main__':
    unittest.main()


class CatalogPriceTests(unittest.TestCase):
    def test_import_keeps_lowest_variation_price(self):
        import io
        from zipfile import ZipFile
        from backend.scrap_lib import own_catalog
        def cell(ref, text):
            return f'<c r="{ref}" t="inlineStr"><is><t>{text}</t></is></c>'
        rows = {2: {'D': own_catalog.SOURCES['Probiotickids']},
                3: {'A': 'Product ID', 'B': 'Product Name', 'G': 'Price'},
                7: {'A': '58017667774', 'B': 'Item One', 'G': '40.80'},
                8: {'A': '58017667774', 'B': 'Item One', 'G': '35.50'},
                9: {'A': '58009537061', 'B': 'Item Two', 'G': 'n/a'}}
        body = ''.join(f'<row r="{n}">' + ''.join(cell(f'{c}{n}', v) for c, v in r.items()) + '</row>' for n, r in rows.items())
        sheet = ('<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>' + body + '</sheetData></worksheet>')
        buf = io.BytesIO()
        with ZipFile(buf, 'w') as z:
            z.writestr('xl/worksheets/sheet1.xml', sheet)
        out = {r['item_id']: r for r in own_catalog.read_xlsx_catalog(buf.getvalue(), 'Probiotickids')}
        self.assertEqual(out['58017667774']['price'], 35.5)
        self.assertEqual(out['58017667774']['variation_count'], 2)
        self.assertNotIn('price', out['58009537061'])

    def test_bundled_catalog_has_prices(self):
        from backend.scrap_lib import own_catalog
        priced = [r for r in own_catalog.bundled_catalog() if r.get('price')]
        self.assertGreater(len(priced), 400)
