import unittest
from backend.stock_after_sales_api import compute


class StockAfterSales(unittest.TestCase):
    def test_subtracts_each_channel_and_flags_negative(self):
        opening = [dict(product_id='a', quantity=10), dict(product_id='b', quantity=2)]
        prods = {'a': dict(name='Alpha', unit='Box'), 'b': dict(name='Beta', unit='Bottle')}
        sales = [dict(channel='shopee_my', product_id='a', units_sold=3), dict(channel='shopee_sg', product_id='a', units_sold=2),
                 dict(channel='clinic', product_id='a', units_sold=1), dict(channel='shopee_my', product_id='b', units_sold=5)]
        rows, un = compute(opening, prods, sales)
        by = {r['name']: r for r in rows}
        self.assertEqual(by['Alpha']['after'], 4)
        self.assertEqual(by['Alpha']['sold_total'], 6)
        self.assertEqual(by['Beta']['after'], -3)
        self.assertEqual(rows[0]['name'], 'Beta')  # negatives first
        self.assertEqual(un, [])

    def test_unmatched_sales_are_listed_not_subtracted(self):
        rows, un = compute([dict(product_id='a', quantity=5)], {'a': dict(name='A')},
                           [dict(channel='shopee_my', product_id=None, item_key='99', name='Mystery', units_sold=4)])
        self.assertEqual(rows[0]['after'], 5)
        self.assertEqual(un[0]['units'], 4)

    def test_product_not_in_snapshot(self):
        rows, _ = compute([], {'z': dict(name='Z')}, [dict(channel='clinic', product_id='z', units_sold=2)])
        self.assertFalse(rows[0]['in_snapshot']); self.assertEqual(rows[0]['after'], -2)


if __name__ == '__main__':
    unittest.main()
