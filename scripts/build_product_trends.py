"""Build data/product_trends.json (+ .js) from the monthly dashboard files in data/ (YYYY-MM.json).

The Product Details page uses it for the month-by-month charts and the "Kept % history by month" table.
Run after adding a new month:   py -m scripts.build_product_trends
"""
import json
import re
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / 'data'


def main():
    months = sorted(p.stem for p in DATA.glob('*.json') if re.fullmatch(r'\d{4}-\d{2}', p.stem))
    products = {}
    for month in months:
        d = json.loads((DATA / f'{month}.json').read_text(encoding='utf-8'))
        fx = (d.get('meta') or {}).get('fx') or 1
        for p in d.get('products', []):
            my, sg = p.get('my') or {}, p.get('sg') or {}
            clinic_units = p.get('s')
            products.setdefault(str(p['id']), {})[month] = {
                'my': {'units': my.get('units') or 0, 'revenue': round(my.get('sales') or 0, 2), 'currency': 'MYR'},
                'sg': {'units': sg.get('units') or 0, 'revenue': round((sg.get('sales') or 0) / fx, 2), 'currency': 'SGD'},
                'clinic': {'units': clinic_units,
                           'revenue': round(clinic_units * p['p'], 2) if clinic_units is not None and p.get('p') else None,
                           'currency': 'MYR'},
            }
    out = {'meta': {'months': months, 'sgCurrency': 'SGD', 'clinicCurrency': 'MYR', 'myCurrency': 'MYR',
                    'note': 'Built from the monthly dashboard files in data/. Shopee revenue excludes platform fees. '
                            'Clinic revenue is units x listed clinic price.'},
           'products': products}
    text = json.dumps(out, ensure_ascii=False, separators=(',', ':'))
    (DATA / 'product_trends.json').write_text(text, encoding='utf-8')
    (DATA / 'product_trends.js').write_text(f'window.FIRSTSTEP_TRENDS = {text};\n', encoding='utf-8')
    print(f'{len(products)} products, months {", ".join(months)}')


if __name__ == '__main__':
    main()
