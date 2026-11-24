"""Stock after sales, straight from uploaded files (nothing is saved).

Files recognised by their content:
  Avixo Inventory Report (.xlsx, sheets "Summary" + "Multiple Expiry")  -> opening stock
  Shopee Business Insights "parentskudetail" (.xlsx, sheet "Top Performing Products") -> units sold (MY / SG from the currency; FirstWell has no Shopee PH)
  (FirstWell has one Shopee SG shop and no Lazada: a Lazada file is refused.)
  TikTok Shop product list (.xlsx, first cell "Analysis date: ...")                  -> items sold

Matching a sale to an Avixo product, in this order:
  1. The remark (Comments column) in Avixo:  MY|item|variation ; SG|item|variation ;
     TT|product id|0     (variation id 0 = the whole listing; old SG1| / SG2| remarks count as SG)
  2. Otherwise the product name, but only when it is a clear match. Name matches are marked "check".
  3. Otherwise the sale is listed as "not matched" so it is never lost silently.
"""
import datetime as dt
import re
from collections import defaultdict

CHANNELS = [('shopee_my', 'Shopee MY'), ('shopee_sg', 'Shopee SG'), ('tiktok', 'TikTok')]
LABEL = dict(CHANNELS)
SLOTS = [('inventory', 'Avixo Inventory')] + CHANNELS
REMARK_NAME = {'shopee_my': 'MY', 'shopee_sg': 'SG', 'tiktok': 'TT'}  # same short names as the file names
SLOT_KIND = {'inventory': 'avixo', 'shopee_my': 'shopee', 'shopee_sg': 'shopee', 'tiktok': 'tiktok'}
SLOT_CURRENCY = {'shopee_my': 'MYR', 'shopee_sg': 'SGD'}
SLOT_MARKET = {'shopee_my': 'MY', 'shopee_sg': 'SG', 'tiktok': 'TT'}
REMARK_MARKET = {'MY': 'MY', 'SG': 'SG', 'SG1': 'SG', 'SG2': 'SG', 'TT': 'TT'}  # one SG shop: old SG1/SG2 remarks count as SG


class FileError(ValueError):
    pass


def num(v):
    try:
        return float(str(v).replace(',', '').strip() or 0)
    except ValueError:
        return 0.0


def txt(v):
    s = str(v if v is not None else '').strip()
    if re.fullmatch(r'\d+\.0', s):
        s = s[:-2]
    return s


# ---------- reading ----------
def read_grid(path, name):
    """Returns (kind, grid, sheets) where grid is the first sheet as a list of rows."""
    ext = name.lower().rsplit('.', 1)[-1]
    if ext == 'xls':
        try:
            import xlrd
        except ImportError:
            raise FileError('Lazada .xls files need the xlrd package on the server.')
        try:
            book = xlrd.open_workbook(str(path))
        except Exception:
            raise FileError(f'{name}: could not open this .xls file.')
        s = book.sheet_by_index(0)
        return {s.name: [s.row_values(i) for i in range(s.nrows)] for s in book.sheets()}
    if ext == 'xlsx':
        import openpyxl
        try:
            wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
        except Exception:
            raise FileError(f'{name}: could not open this .xlsx file.')
        out = {}
        for ws in wb.worksheets:
            try:
                ws.reset_dimensions()  # some exports declare a wrong sheet size
            except Exception:
                pass
            out[ws.title] = [list(r) for r in ws.iter_rows(values_only=True)]
        wb.close()   # Windows: a read-only workbook keeps the file locked until it is closed
        return out
    raise FileError(f'{name}: only .xlsx and .xls files are supported.')


def detect(sheets):
    if 'Summary' in sheets and 'Multiple Expiry' in sheets:
        return 'avixo'
    if 'Top Performing Products' in sheets:
        return 'shopee'
    first = next(iter(sheets.values()), [])
    a1 = txt(first[0][0]) if first and first[0] else ''
    if a1.lower().startswith('data source: lazada'):
        return 'lazada'
    if a1.lower().startswith('analysis date'):
        return 'tiktok'
    return None


def header_index(rows, first_col, limit=12):
    for i, r in enumerate(rows[:limit]):
        if txt(r[0] if r else '') == first_col:
            return i
    return None


def parse_avixo(sheets):
    summ = sheets['Summary']
    hi = header_index(summ, 'ID')
    if hi is None:
        raise FileError('Avixo report: the Summary sheet has no header row.')
    h = [txt(x) for x in summ[hi]]
    col = {n: h.index(n) for n in ('ID', 'Category', 'Name', 'Balance', 'Stock Unit', 'Comments') if n in h}
    if len(col) < 6:
        raise FileError('Avixo report: expected columns ID, Category, Name, Balance, Stock Unit, Comments.')
    prods = []
    for r in summ[hi + 1:]:
        if not r or not isinstance(r[col['ID']], (int, float)):
            continue
        prods.append(dict(id=int(r[col['ID']]), category=txt(r[col['Category']]), name=txt(r[col['Name']]),
                          balance=num(r[col['Balance']]), unit=txt(r[col['Stock Unit']]), comments=txt(r[col['Comments']])))
    when = ''
    for r in summ[:6]:
        if r and txt(r[0]) == 'Date':
            when = next((txt(x) for x in r[1:] if txt(x)), '')
    batches = defaultdict(list)
    me = sheets['Multiple Expiry']
    mh = header_index(me, 'ID')
    if mh is not None:
        mhd = [txt(x) for x in me[mh]]
        if 'Expiry Date' in mhd and 'Stock Balance' in mhd:
            ie, ib = mhd.index('Expiry Date'), mhd.index('Stock Balance')
            for r in me[mh + 1:]:
                if r and isinstance(r[0], (int, float)) and num(r[ib]) > 0:
                    batches[int(r[0])].append((txt(r[ie]), num(r[ib])))
    return dict(products=prods, batches=batches, when=when)


def shopee_slot(sheets, name):
    """Which Shopee box a parentskudetail file belongs to, from the currency in its column names."""
    rows = sheets.get('Top Performing Products') or [[]]
    cur = next((m.group(1) for x in rows[0] for m in [re.search(r'\((MYR|SGD|PHP)\)', txt(x))] if m), None)
    if cur == 'PHP':
        raise FileError(f'{name}: this is a Shopee PH file. FirstWell does not sell on Shopee PH, so it is not used here.')
    found = next((s for s, c in SLOT_CURRENCY.items() if c == cur), None)
    if found is None:
        raise FileError(f'{name}: cannot tell the Shopee market (expected MYR or SGD in the column names).')
    return found


def parse_shopee(sheets, name, slot):
    rows = sheets['Top Performing Products']
    if not rows:
        raise FileError(f'{name}: the Shopee file is empty.')
    h = [txt(x) for x in rows[0]]
    cur = next((m.group(1) for x in h for m in [re.search(r'\((MYR|SGD|PHP)\)', x)] if m), None)
    if cur is None:
        raise FileError(f'{name}: cannot tell the Shopee market (expected MYR, SGD or PHP in the column names).')
    if cur == 'PHP':
        raise FileError(f'{name}: this is a Shopee PH file. FirstWell does not sell on Shopee PH, so it is not used here.')
    if cur != SLOT_CURRENCY[slot]:
        raise FileError(f'{name}: this file is in {cur}, but it was put in {LABEL[slot]} ({SLOT_CURRENCY[slot]}). Put it in the right box.')
    paid = next((i for i, x in enumerate(h) if x.startswith('Units (') and ('Paid' in x or 'Confirmed' in x)), None)
    placed = next((i for i, x in enumerate(h) if x.startswith('Units (Placed')), None)
    if paid is None:
        raise FileError(f'{name}: no "Units (Paid/Confirmed Order)" column.')
    ix = {k: h.index(k) for k in ('Item ID', 'Product', 'Variation ID', 'Variation Name') if k in h}
    if len(ix) < 4:
        raise FileError(f'{name}: expected Item ID, Product, Variation ID and Variation Name columns.')
    lines = []
    with_var = {txt(r[ix['Item ID']]) for r in rows[1:] if r and txt(r[ix['Variation ID']]) not in ('', '-')}
    placed_total = 0.0
    for r in rows[1:]:
        if not r or not txt(r[0]):
            continue
        item, var = txt(r[ix['Item ID']]), txt(r[ix['Variation ID']])
        isvar = var not in ('', '-')
        if not isvar and item in with_var:
            continue  # parent row: its variation rows carry the units
        u = num(r[paid])
        if placed is not None:
            placed_total += num(r[placed])
        if u > 0:
            lines.append(dict(channel=slot, market=SLOT_MARKET[slot], file=name,
                              key=(item, var if isvar else '0'), name=txt(r[ix['Product']]),
                              varname=txt(r[ix['Variation Name']]) if isvar else '', units=u))
    return lines, placed_total


def parse_tiktok(sheets, name):
    rows = next(iter(sheets.values()))
    hi = header_index(rows, 'Product Name', 12)
    if hi is None:
        raise FileError(f'{name}: no "Product Name" header row in the TikTok file.')
    h = [txt(x) for x in rows[hi]]
    if 'Product ID' not in h or 'Items sold' not in h:
        raise FileError(f'{name}: expected TikTok columns "Product ID" and "Items sold".')
    ip, ii, iname = h.index('Product ID'), h.index('Items sold'), h.index('Product Name')
    lines = []
    for r in rows[hi + 1:]:
        if not r or not txt(r[ip]):
            continue
        u = num(r[ii])
        if u > 0:
            lines.append(dict(channel='tiktok', market='TT', file=name, key=(txt(r[ip]), '0'), name=txt(r[iname]), varname='', units=u))
    return lines


# ---------- matching ----------
SIZE = re.compile(r'^\d+(?:\.\d+)?(?:ml|g|mg|kg|l|s)$')
STOP = {'off', 'exp', 'the', 'and', 'for', 'with', 'new', 'big', 'small', 'authentic'}


def tokens(s):
    s = str(s).lower()
    s = re.sub(r'spf\s*(\d+)', r'spf\1', s)
    s = re.sub(r'micro\s*ag', 'microag', s)
    s = re.sub(r'(\d)\s+(ml|g|mg|kg)\b', r'\1\2', s)
    return {w for w in re.findall(r'[a-z0-9]+', s) if w not in STOP and len(w) > 0}


def sizes(tok):
    return {t for t in tok if SIZE.match(t)}


def name_match(prods_tok, text, varname):
    """prods_tok: [(product, tokens)]. Returns (product or None, suggestion product or None)."""
    lt = tokens(text + ' ' + varname)
    need = sizes(tokens(varname))
    scored = []
    for p, pt in prods_tok:
        if not pt:
            continue
        ps = sizes(pt)
        if ps and not ps <= lt:
            continue  # the Avixo product has a size the listing does not mention
        if need and not need <= pt:
            continue  # the chosen variation size is not in this Avixo product
        scored.append((len(pt & lt) / len(pt), p))
    scored.sort(key=lambda x: -x[0])
    if not scored:
        return None, None
    best = scored[0]
    second = scored[1][0] if len(scored) > 1 else 0
    if best[0] >= 0.8 and best[0] - second >= 0.1:
        return best[1], best[1]
    return None, best[1] if best[0] >= 0.5 else None


def candidates(prods_tok, text, varname, n=6):
    """The Avixo products closest to a listing name, best first, for staff to choose from: [{'id', 'name', 'score'}].
    Size rules are used like in name_match; if they remove everything, the closest names are still shown."""
    lt = tokens(text + ' ' + varname)
    need = sizes(tokens(varname))

    def brand(p):
        w = re.findall(r'[a-z0-9]+', str(p['name']).lower())
        return w[0] if w else ''

    out = []
    for p, pt in prods_tok:
        if not pt:
            continue
        sc = len(pt & lt) / len(pt)
        if sc <= 0:
            continue
        if brand(p) in lt:
            sc += 0.3            # same brand (first word of the Avixo name) is the strongest hint
        if not ((sizes(pt) and not sizes(pt) <= lt) or (need and not need <= pt)):
            sc += 0.15           # sizes agree
        out.append((sc, p))
    found = out
    found.sort(key=lambda x: (-x[0], x[1]['name'].lower()))
    return [dict(id=p['id'], name=p['name'], score=round(sc, 2)) for sc, p in found[:n]]


def qty_text(v):
    return str(int(v)) if float(v) == int(v) else f'{v:g}'


def make_remark(sold, date_iso, slot_dates=None):
    """Avixo remark for one product: the sales date as DDMMYYYY, then each platform that sold, e.g. '17112026 MY x1 SG x2'.
    With slot_dates ({channel: ISO date}) every platform keeps the date of its own sales file. Platforms with the same date share one
    date, and different dates are separated by '; ', e.g. '17112026 SG x1; 16112026 TT x2'."""
    def ddmmyyyy(iso):
        try:
            return dt.date.fromisoformat(iso).strftime('%d%m%Y')
        except (TypeError, ValueError):
            return ''
    sold_ch = [c for c, _ in CHANNELS if sold.get(c, 0) > 0]
    groups = {}
    for c in sold_ch:
        groups.setdefault(ddmmyyyy((slot_dates or {}).get(c) or date_iso), []).append(f'{REMARK_NAME[c]} x{qty_text(sold[c])}')
    return '; '.join(' '.join(([d] if d else []) + parts) for d, parts in groups.items())


def file_dates(slot, name, sheets):
    """The day(s) a sales file covers, read from the file (TikTok) or its name (Shopee): list of dates."""
    out = []
    first = next(iter(sheets.values()), [])
    a1 = txt(first[0][0]) if first and first[0] else ''
    try:
        if slot == 'tiktok':
            out = [dt.datetime.strptime(x, '%d/%m/%Y').date() for x in re.findall(r'\d{2}/\d{2}/\d{4}', a1)]
        elif slot.startswith('shopee'):
            m = re.search(r'(\d{8})_(\d{8})', name)
            if m:
                out = [dt.datetime.strptime(x, '%Y%m%d').date() for x in m.groups()]
    except ValueError:
        out = []
    return out


def fefo(batches, qty, today=None):
    today = today or dt.date.today()

    def d(s):
        try:
            return dt.datetime.strptime(s, '%d/%m/%Y').date()
        except ValueError:
            return None
    order = sorted(batches, key=lambda b: (d(b[0]) is None, (d(b[0]) or today) < today, d(b[0]) or dt.date.max))
    out, left = [], qty
    for e, q in order:
        if left <= 0:
            break
        t = min(left, q)
        out.append(f"{e or 'no expiry'} x{int(t) if t == int(t) else t}")
        left -= t
    return '; '.join(out)


def match_reference(ref, unmatched, ref_alias, saved_links, paired, today):
    """Second pass for sales not in the uploaded Avixo report: look them up in FirstStep's Avixo.
    Order: a pairing saved for FirstStep's Avixo, a saved Shopee link to an FS-<id> product, then a clear name match.
    Returns (still unmatched, ref result {label, when, rows, products})."""
    rprods = ref['products']
    by_id = {p['id']: p for p in rprods}
    by_sid = {str(p['id']): p for p in rprods}
    norm = lambda t: re.sub(r'[^a-z0-9]', '', str(t or '').lower())
    fs_links = {}
    for k, v in (saved_links or {}).items():
        aid, pname = (v if isinstance(v, (tuple, list)) else (v, None))
        aid = str(aid)
        if aid.upper().startswith('FS-') and aid[3:] in by_sid and (pname is None or norm(by_sid[aid[3:]]['name']) == norm(pname)):
            fs_links[k] = by_sid[aid[3:]]['id']
    rtok = [(p, tokens(p['name'])) for p in rprods]
    sold = defaultdict(lambda: defaultdict(float)); checks = defaultdict(list); left = []
    for u in unmatched:
        keys = ((u['market'], u['item'], u['var_key']), (u['market'], u['item'], '0'))
        pid, how = None, ''
        for k in keys:
            if str(ref_alias.get(k)) in by_sid:
                pid, how = by_sid[str(ref_alias[k])]['id'], 'alias'
                paired.append(dict(channel=u['channel'], market=u['market'], item=u['item'], variation=k[2], name=u['name'],
                                   var_name=u['variation'], units=u['units'], avixo_id=pid, avixo_name=by_id[pid]['name'],
                                   source='firststep'))
                break
        if pid is None:
            pid = fs_links.get(keys[0]) or fs_links.get(keys[1])
            how = 'link'
        if pid is None:
            p, _ = name_match(rtok, u['name'], u['variation'] or '')
            pid, how = (p['id'], 'name') if p else (None, '')
        if pid is None:
            left.append(dict(u, ref_candidates=candidates(rtok, u['name'], u['variation'] or '')))
            continue
        sold[pid][u['ch']] += u['units']
        if how == 'name':
            checks[pid].append(f"{u['channel']}: matched by product name, please check")
    rows = []
    for pid, by in sold.items():
        p = by_id[pid]; total = sum(by.values())
        rows.append(dict(id=pid, name=p['name'], unit=p['unit'], before=p['balance'], sold={c: by.get(c, 0.0) for c, _ in CHANNELS},
                         total=total, after=p['balance'] - total, expiry=fefo(p.get('batches') or [], total, today),
                         check='; '.join(dict.fromkeys(checks[pid]))))
    rows.sort(key=lambda r: r['name'].lower())
    return left, dict(label=ref.get('label') or "FirstStep's Avixo", when=ref.get('when'), rows=rows,
                      products=sorted(({'id': p['id'], 'name': p['name']} for p in rprods), key=lambda x: x['name'].lower()))


def calculate(files, today=None, saved_links=None, aliases=None, ref=None):
    """files: [(slot, filename, sheets)]. Returns the result dict.
    aliases: pairings staff chose on the page {(market, item, variation): Avixo ID or (Avixo ID, source)} (inv_listing_aliases).
      source 'firststep' = a product in FirstStep's Avixo (the reference below); anything else = the uploaded report.
    ref: FirstStep's Avixo {label, when, products: [{id, name, unit, balance, batches}]} (backend.firststep_ref). Sales not
      found in the uploaded report are looked up there and returned separately in result['ref'] — never combined.
    saved_links: {(market, item id, variation id): (Avixo ID, product name)} from the Shopee links saved on the website.
    The same product has different IDs in the two Avixo accounts (FirstStep and FirstStep PJ), so a saved link is used only
    when the report's product with that ID has the same name; otherwise the product is found by its exact name."""
    avixos, sales_lines, notes, used = [], [], [], []
    placed_diff = []
    dates = {}
    for slot, name, sheets in files:
        kind = detect(sheets)
        if kind is None:
            raise FileError(f'{name}: not recognised. Upload the original Avixo Inventory Report and Shopee / TikTok sales files.')
        if kind == 'lazada':
            raise FileError(f'{name}: this is a Lazada file. FirstWell does not sell on Lazada, so it is not used here.')
        if kind == 'shopee' and SLOT_KIND.get(slot) == 'shopee':
            # The shop is decided by the file's currency, not by the box or the file name (staff mix up MY/SG names).
            real = shopee_slot(sheets, name)
            if real != slot:
                notes.append(f'{name} was in the {LABEL[slot]} box but it is a {LABEL[real]} file ({SLOT_CURRENCY[real]}), '
                             f'so it is counted as {LABEL[real]}.')
                slot = real
        if slot != 'inventory':
            dates[slot] = file_dates(slot, name, sheets)
        if kind != SLOT_KIND[slot]:
            raise FileError(f'{name}: this looks like a {kind.title()} file, but it was put in the {dict(SLOTS)[slot]} box.')
        if kind == 'avixo':
            a = parse_avixo(sheets); a['file'] = name; avixos.append(a); used.append(dict(file=name, kind='Avixo inventory', detail=a['when']))
        elif kind == 'shopee':
            lines, placed = parse_shopee(sheets, name, slot)
            sales_lines += lines
            used.append(dict(file=name, kind=LABEL[slot], detail=f'{sum(l["units"] for l in lines):g} units'))
            if abs(placed - sum(l['units'] for l in lines)) > 0.01:
                placed_diff.append(name)
        else:
            lines = parse_tiktok(sheets, name); sales_lines += lines
            used.append(dict(file=name, kind='TikTok', detail=f'{sum(l["units"] for l in lines):g} units'))
    if not avixos:
        raise FileError('Upload the Avixo Inventory Report (the file named Inventory_Report_...).')
    if len(avixos) > 1:
        def key(a):
            try:
                return dt.datetime.strptime(a['when'], '%d/%m/%Y %I:%M %p')
            except ValueError:
                return dt.datetime.min
        avixos.sort(key=key)
        notes.append(f'{len(avixos)} inventory reports were uploaded. The newest one ({avixos[-1]["file"]}, {avixos[-1]["when"]}) is used.')
    inv = avixos[-1]
    prods = inv['products']
    if len(prods) < 30:
        notes.append(f'The Avixo Inventory Report has only {len(prods)} products, so it was probably exported with a search or '
                     'filter. Export the full Inventory Report (no search) so every sold product can be found.')
    by_id = {p['id']: p for p in prods}
    links = {}
    for p in prods:
        for part in p['comments'].split(';'):
            f = [x.strip() for x in part.strip().split('|')]
            if len(f) >= 3 and f[0].upper() in REMARK_MARKET:
                links[(REMARK_MARKET[f[0].upper()], f[1], f[2])] = p['id']
    by_text = {str(p['id']).strip(): p['id'] for p in prods}
    norm = lambda t: re.sub(r'[^a-z0-9]', '', str(t or '').lower())
    by_name = {}
    for p in prods:
        by_name.setdefault(norm(p['name']), p['id'])
    saved = {}
    for k, v in (saved_links or {}).items():
        aid, pname = (v if isinstance(v, (tuple, list)) else (v, None))
        aid = str(aid)
        aid = aid[3:] if aid.upper().startswith('FS-') else aid
        pid = by_text.get(aid)
        if pid is not None and (pname is None or norm(by_id[pid]['name']) == norm(pname)):
            saved[k] = pid
        elif pname and norm(pname) in by_name:
            saved[k] = by_name[norm(pname)]
    ptok = [(p, tokens(p['name'])) for p in prods]
    by_sid = {str(p['id']): p for p in prods}
    own_alias, ref_alias = {}, {}
    for k, v in (aliases or {}).items():
        aid, src = (v if isinstance(v, (tuple, list)) else (v, 'firstwell'))
        (ref_alias if src == 'firststep' else own_alias)[k] = str(aid)
    aliases = own_alias
    paired = []
    sold = defaultdict(lambda: defaultdict(float)); checks = defaultdict(list); unmatched = []
    for ln in sales_lines:
        item, var = ln['key']
        pid = links.get((ln['market'], item, var)) or links.get((ln['market'], item, '0'))
        how = 'remark'
        if pid is None and aliases:   # a pairing staff saved earlier
            for k in ((ln['market'], item, var), (ln['market'], item, '0')):
                if str(aliases.get(k)) in by_sid:
                    pid, how = by_sid[str(aliases[k])]['id'], 'alias'
                    paired.append(dict(channel=LABEL[ln['channel']], market=ln['market'], item=item, variation=k[2], name=ln['name'],
                                       var_name=ln['varname'], units=ln['units'], avixo_id=pid, avixo_name=by_id[pid]['name'],
                                       source='firstwell'))
                    break
        if pid is None:
            pid = saved.get((ln['market'], item, var)) or saved.get((ln['market'], item, '0'))
            how = 'link'
        if pid is None:
            p, sug = name_match(ptok, ln['name'], ln['varname'])
            pid, how = (p['id'], 'name') if p else (None, 'none')
        if pid is None:
            unmatched.append(dict(channel=LABEL[ln['channel']], ch=ln['channel'], file=ln['file'], market=ln['market'], item=item, var_key=var, variation=ln['varname'], name=ln['name'],
                                  units=ln['units'], suggestion=(f"{sug['id']} {sug['name']}" if sug else ''),
                                  candidates=candidates(ptok, ln['name'], ln['varname'])))
            continue
        sold[pid][ln['channel']] += ln['units']
        if how == 'name':
            checks[pid].append(f'{LABEL[ln["channel"]]}: matched by product name, please check')
    rows = []
    for pid, by in sold.items():
        p = by_id[pid]; total = sum(by.values())
        rows.append(dict(id=pid, name=p['name'], unit=p['unit'], before=p['balance'], sold={c: by.get(c, 0.0) for c, _ in CHANNELS},
                         total=total, after=p['balance'] - total, expiry=fefo(inv['batches'].get(pid, []), total, today),
                         check='; '.join(dict.fromkeys(checks[pid]))))
    rows.sort(key=lambda r: r['name'].lower())
    ref_out = None
    if ref and ref.get('products'):
        unmatched, ref_out = match_reference(ref, unmatched, ref_alias, saved_links, paired, today)
    used_ch = [c for c, _ in CHANNELS if any(l['channel'] == c for l in sales_lines)]
    for c, label in CHANNELS:
        if c not in used_ch:
            notes.append(f'No {label} sales file was uploaded (or it has no sales), so {label} sales are not deducted.')
    if placed_diff:
        notes.append('Shopee units use Paid / Confirmed orders. Placed orders are different in: ' + ', '.join(placed_diff) + '.')
    all_days = [d for v in dates.values() for d in v]
    sales_date = max(all_days).isoformat() if all_days else None
    if len({d for v in dates.values() for d in v[-1:]}) > 1:
        notes.append('The sales files are for different days: ' + ', '.join(f'{LABEL[k]} {v[-1].strftime("%d/%m/%Y")}' for k, v in dates.items() if v) + '. Each platform keeps the date of its own file in the remark. To use one date for all, change the sales date.')
    slot_dates = {k: v[-1].isoformat() for k, v in dates.items() if v}
    for r in rows + (ref_out['rows'] if ref_out else []):
        r['remark'] = make_remark(r['sold'], sales_date, slot_dates)
    if any(r['after'] < 0 for r in rows):
        notes.append('Some products would go below zero in the Avixo report. Check them before updating Avixo.')
    return dict(inventory=dict(file=inv['file'], when=inv['when'], products=len(prods)), files=used, notes=notes, sales_date=sales_date, slot_dates=slot_dates,
                channels=[dict(id=c, label=l) for c, l in CHANNELS if c in used_ch], rows=rows,
                unmatched=sorted(unmatched, key=lambda u: -u['units']), paired=paired, ref=ref_out,
                products=sorted(({'id': p['id'], 'name': p['name']} for p in prods), key=lambda x: x['name'].lower()))
