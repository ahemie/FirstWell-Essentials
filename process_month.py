#!/usr/bin/env python3
"""
FirstWell Essentials Dashboard - monthly data processor (reference implementation)

Reads the six monthly files, matches Shopee listings to Avixo products, runs the
data checks, and writes one JSON file that dashboard/index.html reads.

Usage:
  python3 process_month.py \
    --month 2026-09 \
    --inventory  Inventory_Report_01-10-2026.xlsx \
    --movement   Inventory_Movement_Report_Sep.xlsx \
    --my-price   mass_update_sales_info_994773440_....xlsx \
    --my-perf    parentskudetail_MY_20260901_20260930.xlsx \
    --sg-price   mass_update_sales_info_1344693217_....xlsx \
    --sg-perf    parentskudetail_SG_20260901_20260930.xlsx \
    --fx 3.19 \
    --out dashboard/data/2026-09.json

Requires: Python 3.9+, openpyxl  (pip install openpyxl)

See SPEC.md for every rule used here.
"""
import argparse, collections, datetime as dt, io, json, re, sys, zipfile

import openpyxl

# ---------------------------------------------------------------- file helpers

def open_workbook(path):
    """Open an xlsx. Shopee exports sometimes contain activePane="bottom_left"
    (invalid XML value) which openpyxl rejects; repair it in memory."""
    try:
        return openpyxl.load_workbook(path, data_only=True)
    except ValueError:
        buf = io.BytesIO()
        # Close the source zip: on Windows an open handle blocks deleting the temp file.
        with zipfile.ZipFile(path) as src, zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as dst:
            for item in src.infolist():
                data = src.read(item.filename)
                if item.filename.startswith('xl/worksheets/') and item.filename.endswith('.xml'):
                    data = re.sub(rb'activePane="[^"]*"', b'activePane="bottomLeft"', data)
                dst.writestr(item, data)
        buf.seek(0)
        return openpyxl.load_workbook(buf, data_only=True)


def num(x):
    if x is None or x == '' or x == '-':
        return None
    if isinstance(x, (int, float)):
        return float(x)
    try:
        return float(str(x).replace(',', '').replace('%', '').strip())
    except ValueError:
        return None


def parse_date(s):
    if isinstance(s, dt.datetime):
        return s.date()
    try:
        return dt.datetime.strptime(str(s).strip(), '%d/%m/%Y').date()
    except ValueError:
        return None


def table(ws, header_row):
    """Return (header list, data rows) using a 1-based header row number."""
    rows = list(ws.iter_rows(values_only=True))
    header = [str(h).strip() if h is not None else '' for h in rows[header_row - 1]]
    return header, rows[header_row:]


def col(header, name):
    try:
        return header.index(name)
    except ValueError:
        sys.exit(f'Column "{name}" not found. Columns are: {header}')


def find_header_row(ws, first_cell, max_scan=12):
    for i, row in enumerate(ws.iter_rows(values_only=True, max_row=max_scan), start=1):
        if row and str(row[0]).strip() == first_cell:
            return i
    sys.exit(f'Header row starting with "{first_cell}" not found in sheet {ws.title}')

# ---------------------------------------------------------------- readers

def read_inventory(path):
    """Avixo Inventory Report (month-end snapshot).
    Summary sheet: one row per product (ID, Category, Name, Latest Cost Price, Price, Balance, Comments).
    Multiple Expiry sheet: one row per batch (Expiry Date, Stock Balance, stock values)."""
    wb = open_workbook(path)
    ws = wb['Summary']
    h, rows = table(ws, find_header_row(ws, 'ID'))
    I = {k: col(h, k) for k in ['ID', 'Category', 'Name', 'Latest Cost Price', 'Price', 'Balance', 'Stock Unit', 'Comments']}
    products = []
    for r in rows:
        if not r or not r[I['Name']]:
            continue
        products.append(dict(
            id=r[I['ID']], name=str(r[I['Name']]).strip(), cat=r[I['Category']] or 'Unknown',
            unit=r[I['Stock Unit']], latest_cost=num(r[I['Latest Cost Price']]), price=num(r[I['Price']]),
            summary_balance=num(r[I['Balance']]), comments=r[I['Comments']]))
    ws = wb['Multiple Expiry']
    h, rows = table(ws, find_header_row(ws, 'ID'))
    J = {k: col(h, k) for k in ['Name', 'Expiry Date', 'Stock Balance', 'Stock Value Using Latest Cost Price', 'Stock Value Using Price to Patient']}
    batches = collections.defaultdict(list)
    for r in rows:
        if not r or not r[J['Name']]:
            continue
        batches[str(r[J['Name']]).strip()].append(dict(
            expiry=parse_date(r[J['Expiry Date']]) if r[J['Expiry Date']] else None,
            qty=num(r[J['Stock Balance']]) or 0,
            value_cost=num(r[J['Stock Value Using Latest Cost Price']]) or 0,
            value_retail=num(r[J['Stock Value Using Price to Patient']]) or 0))
    date_cell = next((r[2] for r in wb['Summary'].iter_rows(values_only=True, max_row=6) if r and r[0] == 'Date'), None)
    return products, batches, date_cell


def read_movement(path):
    """Avixo Drug Movement Report for the month. Sold is negative (units out)."""
    ws = open_workbook(path).worksheets[0]
    h, rows = table(ws, find_header_row(ws, 'Category'))
    I = {k: col(h, k) for k in ['Name', 'Cost Price', 'Stock Unit', 'Sold', 'Adjust', 'Closing Balance']}
    out = {}
    for r in rows:
        if not r or not r[I['Name']]:
            continue
        out[str(r[I['Name']]).strip()] = dict(
            sold=-(num(r[I['Sold']]) or 0), adjust=num(r[I['Adjust']]) or 0,
            closing=num(r[I['Closing Balance']]), cost=num(r[I['Cost Price']]), unit=r[I['Stock Unit']])
    period = next((r[2] for r in ws.iter_rows(values_only=True, max_row=6) if r and r[0] == 'Date'), None)
    return out, period


def read_shopee_price(path):
    """Shopee mass-update sales info export. Header on row 3, data from row 7.
    Returns {(item_id, variation_id): price} and {item_id: [prices]}."""
    ws = open_workbook(path).worksheets[0]
    h, rows = table(ws, 3)
    I = {k: col(h, k) for k in ['Product ID', 'Variation ID', 'Price']}
    by_var, by_item = {}, collections.defaultdict(list)
    for r in rows[3:]:  # skip the 3 instruction rows under the header
        if not r or not r[I['Product ID']]:
            continue
        item, var, price = str(r[I['Product ID']]).strip(), str(r[I['Variation ID']] or '').strip(), num(r[I['Price']])
        by_var[(item, var)] = price
        by_item[item].append(price)
    return by_var, by_item


def read_shopee_perf(path, units_col, sales_col):
    """Shopee product performance (parentskudetail), sheet 'Top Performing Products'.
    Parent rows have Variation ID '-'; variation rows carry the variation ID."""
    ws = open_workbook(path)['Top Performing Products']
    h, rows = table(ws, 1)
    I = {k: col(h, k) for k in ['Item ID', 'Product', 'Variation ID', units_col, sales_col]}
    parent, variation = {}, {}
    for r in rows:
        if not r or not r[I['Item ID']]:
            continue
        item, var = str(r[I['Item ID']]).strip(), str(r[I['Variation ID']]).strip()
        units, sales = num(r[I[units_col]]) or 0, num(r[I[sales_col]]) or 0
        if var == '-':
            parent[item] = dict(units=units, sales=sales, name=r[I['Product']])
        else:
            variation[(item, var)] = dict(units=units, sales=sales)
    return parent, variation


def parse_links(comments):
    """Avixo Comments field: 'MY|<item id>|<variation id or 0>; SG|<item id>|<variation id or 0>'"""
    links = []
    for part in str(comments or '').strip().split(';'):
        part = part.strip()
        if part.count('|') == 2:
            market, item, var = [x.strip() for x in part.split('|')]
            links.append((market, item, var))
    return links

# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--month', required=True, help='YYYY-MM of the movement period')
    ap.add_argument('--inventory', required=True)
    ap.add_argument('--movement', required=True)
    ap.add_argument('--my-price', required=True)
    ap.add_argument('--my-perf', required=True)
    ap.add_argument('--sg-price', help='Shopee SG price file (leave out if the shop has no SG)')
    ap.add_argument('--sg-perf', help='Shopee SG sales file (leave out if the shop has no SG)')
    ap.add_argument('--fx', type=float, default=1.0, help='MYR per 1 SGD (only used with SG files)')
    ap.add_argument('--links', help='Shopee links sheet (FirstWell_Shopee_Links_MY.xlsx). Used instead of the Avixo '
                    'Comments column. FS-<id> rows are FirstStep Avixo products: added with 0 stock here.')
    ap.add_argument('--stock-date', help='YYYY-MM-DD the stock snapshot represents (default: first day after the month)')
    ap.add_argument('--out', required=True)
    a = ap.parse_args()

    y, m = map(int, a.month.split('-'))
    stock_date = dt.date.fromisoformat(a.stock_date) if a.stock_date else (dt.date(y + (m == 12), m % 12 + 1, 1))

    products, batches, inv_date = read_inventory(a.inventory)
    movement, mov_period = read_movement(a.movement)
    my_pv, my_pi = read_shopee_price(a.my_price)
    sg_pv, sg_pi = read_shopee_price(a.sg_price) if a.sg_price else ({}, {})
    my_par, my_var = read_shopee_perf(a.my_perf, 'Units (Confirmed Order)', 'Sales (Confirmed Order) (MYR)')
    sg_par, sg_var = read_shopee_perf(a.sg_perf, 'Units (Paid Order)', 'Sales (Paid Order) (SGD)') if a.sg_perf else ({}, {})
    shop = {'MY': (my_par, my_var, my_pi, my_pv, 1.0), 'SG': (sg_par, sg_var, sg_pi, sg_pv, a.fx)}

    def clean_id(v):
        t = str(v if v is not None else '').strip()
        return t[:-2] if t.endswith('.0') and t[:-2].isdigit() else t
    sheet_links = None
    if a.links:
        from backend.links_api import read_links_workbook
        sheet_links = collections.defaultdict(list)
        for market in ('MY', 'SG'):
            try:
                rows, problems, extra = read_links_workbook(a.links, market)
            except ValueError:
                continue
            for r in rows:
                if r['avixo'] != 'FREE':
                    sheet_links[r['avixo']].append((market, r['item'], r['var']))
        have = {clean_id(p['id']) for p in products}
        for fs_id in sorted(k for k in sheet_links if k.startswith('FS-') and k not in have):
            products.append(dict(id=fs_id, name=extra.get(fs_id, fs_id), cat='FirstStep stock', unit=None, latest_cost=None,
                                 price=None, summary_balance=None, comments='', firststep=True))
    links_for = (lambda p: sheet_links.get(clean_id(p['id']), [])) if sheet_links is not None else (lambda p: parse_links(p['comments']))
    link_use = collections.Counter(l for p in products for l in links_for(p))
    report = collections.Counter()
    out = []
    inv_names = set()
    for p in products:
        name = p['name']; inv_names.add(name)
        mv = movement.get(name)
        bs = batches.get(name, [])
        q = sum(b['qty'] for b in bs)
        rec = dict(id=p['id'], n=name, c=p['cat'], u=p['unit'], lc=p['latest_cost'], p=p['price'],
                   q=q, qs=p['summary_balance'],
                   val=round(sum(b['value_cost'] for b in bs), 2), ret=round(sum(b['value_retail'] for b in bs), 2),
                   s=mv['sold'] if mv else 0, adj=mv['adjust'] if mv else 0, mc=mv['closing'] if mv else None)
        dated = sorted([[b['expiry'].isoformat(), b['qty']] for b in bs if b['qty'] and b['expiry']])
        if dated:
            rec['b'] = dated
        rec['x'] = dated[0][0] if dated else None

        if p.get('firststep'):
            rec['fl'] = ['Stock kept at FirstStep']
        for market, item, var in links_for(p):
            if market not in shop:
                continue
            par, varp, price_item, price_var, fx = shop[market]
            listed = item in price_item
            if var != '0':
                perf = varp.get((item, var), dict(units=0, sales=0))
                price = price_var.get((item, var))
            else:
                perf = par.get(item, dict(units=0, sales=0))
                prices = [x for x in price_item.get(item, []) if x]
                price = min(prices) if prices else None
                if len(prices) > 1:
                    report[f'{market}: listing with several variation prices (lowest used)'] += 1
            if link_use[(market, item, var)] > 1:
                report[f'{market}: same listing linked from several Avixo products'] += 1
                rec.setdefault('fl', []).append('Shared Shopee listing')
            d = rec.setdefault(market.lower(), dict(listed=False, units=0, sales=0, prices=[], links=0))
            d['listed'] = d['listed'] or listed
            d['units'] += perf['units']
            d['sales'] = round(d['sales'] + perf['sales'] * fx, 2)
            d['links'] += 1
            if price:
                d['prices'].append(round(price * fx, 2))
            if not listed:
                report[f'{market}: Avixo link not found in price file'] += 1

        for mk in ('my', 'sg'):
            if mk in rec:
                d = rec[mk]
                d['price'] = min(d['prices']) if d['prices'] else None
                d['nprice'] = len(d['prices'])
                del d['prices']

        # data checks (see SPEC.md section 6)
        if rec['mc'] is not None and abs(rec['mc'] - q) > 5:
            rec['mm'] = 1
        if rec['qs'] is not None and abs(rec['qs'] - q) > 0.001:
            rec['bs'] = 1
        e_units = (rec.get('my') or {}).get('units', 0) + (rec.get('sg') or {}).get('units', 0)
        adj_out = -min(0, rec['adj'] or 0)
        if (rec.get('my') or rec.get('sg')) and abs(adj_out - e_units) > max(5, 0.5 * max(adj_out, e_units)):
            rec['eg'] = adj_out
        out.append(rec)

    for name, mv in movement.items():
        if name not in inv_names:
            out.append(dict(id=None, n=name, c='Unknown', u=mv['unit'], lc=mv['cost'], p=None, q=0, qs=None, val=0, ret=0,
                            s=mv['sold'], adj=mv['adjust'], mc=mv['closing'], x=None, onlyMov=1))
            report['Product in Movement Report but not in Inventory Report'] += 1

    my_file_units = sum(v['units'] for v in my_par.values()); my_file_sales = sum(v['sales'] for v in my_par.values())
    sg_file_units = sum(v['units'] for v in sg_par.values()); sg_file_sales = sum(v['sales'] for v in sg_par.values())
    meta = dict(month=a.month, label=dt.date(y, m, 1).strftime('%b %Y'), today=stock_date.isoformat(),
                invSnapshot=str(inv_date), movement=str(mov_period), fx=a.fx,
                myFileUnits=my_file_units, myFileSales=round(my_file_sales), sgFileUnits=sg_file_units, sgFileSalesSGD=round(sg_file_sales),
                invProducts=len(products), invBatches=sum(len(v) for v in batches.values()), movProducts=len(movement),
                myListings=len(my_pv), sgListings=len(sg_pv))
    payload = json.dumps(dict(meta=meta, products=out), separators=(',', ':'))
    with open(a.out, 'w') as f:
        f.write(payload)
    # Also write a .js copy and update months.js, so dashboard/index.html works when opened
    # by double-click (browsers block fetch() of local files but allow <script> files).
    import os
    data_dir = os.path.dirname(os.path.abspath(a.out))
    with open(os.path.join(data_dir, a.month + '.js'), 'w') as f:
        f.write('window.DASHBOARD_DATA = window.DASHBOARD_DATA || {};\n')
        f.write('window.DASHBOARD_DATA[' + json.dumps(a.month) + '] = ' + payload + ';\n')
    months_path = os.path.join(data_dir, 'months.json')
    months = json.load(open(months_path)) if os.path.exists(months_path) else []
    months = [x for x in months if x['key'] != a.month] + [dict(key=a.month, label=meta['label'], file=os.path.basename(a.out))]
    months.sort(key=lambda x: x['key'])
    with open(months_path, 'w') as f:
        json.dump(months, f, indent=2)
    with open(os.path.join(data_dir, 'months.js'), 'w') as f:
        f.write('window.DASHBOARD_MONTHS = ' + json.dumps(months, indent=2) + ';\n')

    # ---------------- check report (compare with SPEC.md section 8)
    my_u = sum((r.get('my') or {}).get('units', 0) for r in out); my_s = sum((r.get('my') or {}).get('sales', 0) for r in out)
    sg_u = sum((r.get('sg') or {}).get('units', 0) for r in out); sg_s = sum((r.get('sg') or {}).get('sales', 0) for r in out)
    print(f'Products: {len(out)}   stock value (latest cost): RM {sum(r["val"] for r in out):,.0f}   stock units: {sum(r["q"] for r in out):,.0f}')
    print(f'Clinic units sold: {sum(r["s"] or 0 for r in out):,.0f}   clinic sales (units x clinic price): RM {sum((r["s"] or 0) * (r["p"] or 0) for r in out):,.0f}')
    print(f'Shopee MY matched: {my_u:,.0f} of {my_file_units:,.0f} units, RM {my_s:,.0f} of RM {my_file_sales:,.0f} ({my_s / my_file_sales * 100 if my_file_sales else 0:.1f}%)')
    print(f'Shopee SG matched: {sg_u:,.0f} of {sg_file_units:,.0f} units, RM {sg_s:,.0f} of RM {sg_file_sales * a.fx:,.0f} ({sg_s / (sg_file_sales * a.fx) * 100 if sg_file_sales else 0:.1f}%)')
    print(f'Flags: stock differs >5 units: {sum(1 for r in out if r.get("mm"))}   batch total != summary: {sum(1 for r in out if r.get("bs"))}   e-com deduction vs Shopee units: {sum(1 for r in out if r.get("eg") is not None)}')
    for k, v in sorted(report.items()):
        print(f'  {k}: {v}')
    print(f'Wrote {a.out}')


if __name__ == '__main__':
    main()
