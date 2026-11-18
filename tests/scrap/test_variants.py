import unittest

from backend.scrap_lib.variants import expand_variations, variation_title


class VariantTests(unittest.TestCase):
    def test_size_list_becomes_one_product_per_size(self):
        title = '[EXP 04/27] Cetaphil Moisturizing Cream 💧 50g / 100g / 453g | Face & Body 🌿 | Dry & Sensitive Skin'
        names = ['100g', '453g', '50g']
        got = [variation_title(title, n, names) for n in names]
        self.assertEqual(got, ['[EXP 04/27] Cetaphil Moisturizing Cream 100g',
                               '[EXP 04/27] Cetaphil Moisturizing Cream 453g',
                               '[EXP 04/27] Cetaphil Moisturizing Cream 50g'])

    def test_two_sizes_keep_expiry_note(self):
        title = 'ATONO2 OXYGEN BATH & SHAMPOO 300G/50g | EXP: 07/28 & 12/27 | Moisturize | Baby sensitive skin'
        self.assertEqual(variation_title(title, '50g', ['300g', '50g']), 'ATONO2 OXYGEN BATH & SHAMPOO 50g | EXP: 07/28 & 12/27')

    def test_flavours_and_slash_list_removed(self):
        title = "Buds Children's Toothpaste With Xylitol 1-3years Green Apple/Strawberry/Blackcurrant | 50ml | EXP:03/28"
        names = ['Blackcurrant', 'Green Apple', 'Strawberry']
        self.assertEqual(variation_title(title, 'Strawberry', names), "Buds Children's Toothpaste With Xylitol 1-3years Strawberry | EXP:03/28")

    def test_each_part_of_a_slash_title(self):
        title = 'Biome ComfyPro Drops 8ml / Biome ImmunoPro Drops 10ml | EXP: 02/2028 & 03/2028'
        names = ['Comfypro Drops 8ml', 'Immunopro Drops 10ml']
        self.assertEqual(variation_title(title, names[1], names), 'Biome ImmunoPro Drops 10ml | EXP: 02/2028 & 03/2028')

    def test_series_listing_uses_each_product_name(self):
        title = 'Zeho Series | Zeho Extra Gentle Cleanser 250ML | Zeho Lotion 280ML'
        names = ['Gentle Cleanser250ML', 'Lotion 280ML']
        self.assertEqual(variation_title(title, names[0], names), 'Zeho Gentle Cleanser 250ML')

    def test_expand_only_items_with_two_named_variations(self):
        rows = [{'item_id': '1', 'title': 'Cream 50g / 100g', 'price': 10, 'variations': [
                    {'id': 'a', 'name': '50g', 'price': 10}, {'id': 'b', 'name': '100g', 'price': 18}]},
                {'item_id': '2', 'title': 'Single', 'price': 5, 'variations': [{'id': 'c', 'name': 'Only', 'price': 5}]},
                {'item_id': '3', 'title': 'Plain', 'price': 7}]
        out = expand_variations(rows)
        self.assertEqual([(r['item_id'], r['title'], r['price']) for r in out],
                         [('1', 'Cream 50g', 10), ('1', 'Cream 100g', 18), ('2', 'Single', 5), ('3', 'Plain', 7)])
        self.assertEqual(out[1]['variation_id'], 'b')
        self.assertNotIn('variations', out[0])


if __name__ == '__main__':
    unittest.main()
