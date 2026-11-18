"""Build the Shopee -> Avixo link review workbook (one-time helper, runs offline).

Usage:
  python -m scripts.build_link_review --inventory "Inventory Report.xlsx" --price mass_update_sales_info_XXXX.xlsx \
      --sales parentskudetail.A.xlsx parentskudetail.B.xlsx --market MY --out FirstWell_Shopee_Links.xlsx

Staff check the sheet, fill "Avixo ID to use", then upload it in Upload Data > Shopee listing links.
Suggestions are only suggestions: similar names (e.g. Frisolac HA vs AR) can be wrong.
"""
import argparse
from collections import defaultdict

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.worksheet.datavalidation import DataValidation

from process_month import read_inventory, read_shopee_perf

from backend.link_match import pick


def read_price_listings(path):
    ws = openpyxl.load_workbook(path, read_only=True, data_only=True).worksheets[0]
    header = None
    rows = []
    for r in ws.iter_rows(values_only=True):
        if header is None:
            if r and 'Product ID' in r and 'Variation ID' in r:
                header = {str(v): i for i, v in enumerate(r) if v}
            continue
        item = str(r[header['Product ID']] or '').strip()
        if not item.isdigit():
            continue
        rows.append(dict(item=item, name=str(r[header['Product Name']] or '').strip(),
                         var=str(r[header['Variation ID']] or '').strip(),
                         var_name=str(r[header.get('Variation Name', -1)] or '').strip() if 'Variation Name' in header else '',
                         price=r[header['Price']] if 'Price' in header else None))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--inventory', required=True)
    ap.add_argument('--price', required=True)
    ap.add_argument('--sales', nargs='*', default=[])
    ap.add_argument('--market', default='MY', choices=['MY', 'SG'])
    ap.add_argument('--out', required=True)
    a = ap.parse_args()

    products, _, _ = read_inventory(a.inventory)
    products = [p for p in products if str(p.get('id') or '').strip()]
    pid = lambda p: str(p['id']).strip()[:-2] if str(p['id']).strip().endswith('.0') else str(p['id']).strip()

    units_item, units_var, names = defaultdict(float), defaultdict(float), {}
    cols = ('Units (Confirmed Order)', 'Sales (Confirmed Order) (MYR)') if a.market == 'MY' else ('Units (Paid Order)', 'Sales (Paid Order) (SGD)')
    for f in a.sales:
        par, var = read_shopee_perf(f, *cols)
        for k, x in par.items():
            units_item[str(k)] += x.get('units') or 0
            names.setdefault(str(k), x.get('name') or '')
        for (k, v), x in var.items():
            units_var[(str(k), str(v))] += x.get('units') or 0

    listings = defaultdict(list)
    for r in read_price_listings(a.price):
        listings[r['item']].append(r)
        names[r['item']] = r['name'] or names.get(r['item'], '')
    for item in names:                       # sold but missing from the price file
        listings.setdefault(item, [dict(item=item, name=names[item], var='', var_name='', price=None)])

    lines = []
    for item, vs in listings.items():
        multi = len(vs) > 1
        for v in (vs if multi else vs[:1]):
            var_name = v['var_name'] if multi else ''
            best, ranked = pick(vs[0]['name'], var_name, products)
            sold = units_var.get((item, v['var']), 0) if multi else units_item.get(item, 0)
            top = ranked[0][1]
            lines.append(dict(market=a.market, item=item, var=v['var'] if multi else '0', name=vs[0]['name'],
                              var_name=var_name, units=sold,
                              sug_id=pid(best or top), sug_name=(best or top)['name'], score=round(ranked[0][0], 3),
                              alt=f"{pid(ranked[1][1])}: {ranked[1][1]['name']}", use=pid(best) if best else '',
                              confident=bool(best)))
    lines.sort(key=lambda x: (-x['units'], x['name'], x['var']))

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Links'
    head = ['Marketplace', 'Shopee item ID', 'Variation ID', 'Shopee product name', 'Variation name', 'Units sold',
            'Suggested Avixo ID', 'Suggested Avixo product', 'Match score', 'Second choice',
            'Avixo ID to use', 'Avixo product (check)']
    ws.append(head)
    yellow = PatternFill('solid', fgColor='FFF4C2')
    green = PatternFill('solid', fgColor='DFF5E9')
    for i, x in enumerate(lines, start=2):
        ws.append([x['market'], x['item'], x['var'], x['name'], x['var_name'], x['units'], x['sug_id'], x['sug_name'],
                   x['score'], x['alt'], x['use'],
                   f'=IF(K{i}="","",IFERROR(VLOOKUP(K{i},\'Avixo products\'!A:B,2,FALSE),IF(UPPER(K{i})="FREE","Free gift (no product)","NOT FOUND - check ID")))'])
        ws.cell(i, 11).fill = green if x['confident'] else yellow
    for c in ws[1]:
        c.font = Font(bold=True, color='FFFFFF')
        c.fill = PatternFill('solid', fgColor='0B3D37')
        c.alignment = Alignment(wrap_text=True, vertical='top')
    for col, w in zip('ABCDEFGHIJKL', [8, 14, 14, 60, 18, 8, 10, 40, 8, 40, 12, 40]):
        ws.column_dimensions[col].width = w
    ws.freeze_panes = 'D2'
    ws.auto_filter.ref = f'A1:L{len(lines) + 1}'

    ps = wb.create_sheet('Avixo products')
    ps.append(['Avixo ID', 'Product name', 'Category'])
    for p in sorted(products, key=lambda p: p['name'].lower()):
        ps.append([pid(p), p['name'], p.get('cat')])
    ps.column_dimensions['A'].width = 10
    ps.column_dimensions['B'].width = 60
    for c in ps[1]:
        c.font = Font(bold=True)

    how = wb.create_sheet('How to use', 0)
    for line in [
        ['Shopee listing links — how to use'],
        [''],
        ['1. Go to sheet "Links". Column K "Avixo ID to use" decides the link. Column L shows the product name for the ID you typed — check it.'],
        ['2. GREEN = matched automatically to the Avixo Inventory Report (same brand, size and variant). Already filled in.'],
        ['3. YELLOW = no clear Avixo product, left empty, so the website leaves it out. To link one anyway, type its Avixo ID in K.'],
        ['4. Free gift / bundle with no Avixo product: type FREE in K. Leave K empty to skip a listing.'],
        ['5. Listings with sizes/flavours have one row per Variation ID — each can go to a different Avixo product.'],
        ['6. Save, then upload this file on the website: Upload Data > Shopee listing links.'],
        ['   Sales already uploaded are re-matched automatically. Do not change columns A-C.'],
        [''],
        [f'Rows: {len(lines)} · pre-filled (green): {sum(x["confident"] for x in lines)} · to check (yellow): {sum(not x["confident"] for x in lines)}'],
    ]:
        how.append(line)
    how['A1'].font = Font(bold=True, size=14)
    how.column_dimensions['A'].width = 120
    wb.active = 1
    wb.save(a.out)
    print(f'{len(lines)} rows, {sum(x["confident"] for x in lines)} pre-filled, saved {a.out}')


if __name__ == '__main__':
    main()
