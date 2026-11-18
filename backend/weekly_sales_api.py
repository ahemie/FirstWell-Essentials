"""Staff-only WEEKLY sales uploads (Shopee MY, Shopee SG, Clinic movement). No inventory involved.

Separate from the monthly uploader. Every import carries an explicit period
(period_start..period_end). A period may not overlap an earlier import for the same channel,
so a day can never be counted twice. Reports add up whole imports that lie inside the chosen range.
Shopee MY and SG are kept in their own currency (no FX); clinic movement is units only.

Routes (all behind the app's staff login + CSRF check):
  POST /api/weekly-sales/preview   file + kind + period_start + period_end -> checks, writes nothing
  POST /api/weekly-sales/accept    same fields + expected_sha256 -> saves
  GET  /api/weekly-sales/summary   ?from=YYYY-MM-DD&to=YYYY-MM-DD
"""
import datetime as dt
import hashlib
import logging
import re
import tempfile
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

from flask import Blueprint, g, jsonify, request
from werkzeug.utils import secure_filename

from process_month import read_movement, read_shopee_perf
from backend.supabase_upload import client, d, detect_kind, ident, iso_date, owners_lookup, product_lookup

bp = Blueprint('weekly_sales_api', __name__, url_prefix='/api/weekly-sales')
LOG = logging.getLogger(__name__)
KIND_CHANNEL = {'my_perf': 'shopee_my', 'sg_perf': 'shopee_sg', 'movement': 'clinic'}
CHANNEL_LABEL = {'shopee_my': 'Shopee MY', 'shopee_sg': 'Shopee SG', 'clinic': 'Clinic'}
CHANNEL_CURRENCY = {'shopee_my': 'MYR', 'shopee_sg': 'SGD', 'clinic': None}
MAX_DAYS = 31


class ReportError(ValueError):
    pass


def parse_date(text, label):
    try:
        return dt.date.fromisoformat(str(text or '').strip())
    except ValueError:
        raise ReportError(f'{label} must be a date (YYYY-MM-DD).')


def check_period(start, end, today=None):
    today = today or dt.date.today()
    if end < start:
        raise ReportError('The end date is before the start date.')
    if (end - start).days + 1 > MAX_DAYS:
        raise ReportError(f'A weekly upload can cover at most {MAX_DAYS} days. For a full month use the monthly uploader.')
    if end > today:
        raise ReportError('The period ends in the future. Upload only after the last day of the period.')


def filename_period(name):
    m = re.search(r'(20\d{6})[_-](20\d{6})', name)
    if not m:
        return None
    try:
        return (dt.datetime.strptime(m.group(1), '%Y%m%d').date(), dt.datetime.strptime(m.group(2), '%Y%m%d').date())
    except ValueError:
        raise ReportError('Invalid date in the file name.')


def fetch_pages(query_builder, page=500):
    rows, start = [], 0
    while True:
        batch = query_builder().range(start, start + page - 1).execute().data or []
        rows.extend(batch)
        if len(batch) < page:
            return rows
        start += page


def parse_report(path, filename, kind, start, end, db):
    """Returns (rows, meta, warnings). Raises ReportError for anything that does not add up."""
    channel = KIND_CHANNEL[kind]
    warnings = []
    rows = []
    if kind in ('my_perf', 'sg_perf'):
        market = 'MY' if kind == 'my_perf' else 'SG'
        units_col = 'Units (Confirmed Order)' if market == 'MY' else 'Units (Paid Order)'
        money_col = 'Sales (Confirmed Order) (MYR)' if market == 'MY' else 'Sales (Paid Order) (SGD)'
        parents, variations = read_shopee_perf(str(path), units_col, money_col)
        if not parents:
            raise ReportError('No Shopee product rows found in this file.')
        grouped = defaultdict(list)
        for (item, _var), info in variations.items():
            grouped[ident(item)].append(info)
        for item, parts in grouped.items():  # same integrity check as the monthly uploader
            p = parents.get(item)
            if p is None:
                raise ReportError(f'Variation rows for Shopee item {item} have no parent row.')
            vu = sum(Decimal(str(x.get('units') or 0)) for x in parts)
            vr = sum(Decimal(str(x.get('sales') or 0)) for x in parts)
            if abs(vu - Decimal(str(p.get('units') or 0))) > Decimal('.01') or abs(vr - Decimal(str(p.get('sales') or 0))) > Decimal('.05'):
                raise ReportError(f'Variation sales do not add up to the parent for Shopee item {item}.')
        _exact, only_parent = owners_lookup(db, market)
        currency = CHANNEL_CURRENCY[channel]
        for item, val in parents.items():
            key = ident(item)
            rows.append(dict(channel=channel, item_key=key, name=str(val.get('name') or ''),
                             product_id=only_parent.get(key), units_sold=d(val.get('units') or 0),
                             sales_amount=d(val.get('sales') or 0), currency=currency))
        fp = filename_period(filename)
        if fp and fp != (start, end):
            raise ReportError(f'The file name says {fp[0]} to {fp[1]} but you entered {start} to {end}.')
        if not fp:
            warnings.append('The file name has no dates, so the period cannot be double-checked. Make sure the dates you entered are the ones you exported.')
        warnings.append('Only product-level (parent) totals are stored. Variation rows were used for checking only.')
    else:  # clinic movement
        move, period = read_movement(str(path))
        m = re.search(r'From:\s*(\d{2}/\d{2}/\d{4})\s*-\s*To:\s*(\d{2}/\d{2}/\d{4})', str(period))
        if not m:
            raise ReportError('The movement report has no readable From/To dates. Upload the original workbook.')
        wb_start, wb_end = iso_date(m.group(1)), iso_date(m.group(2))
        if (wb_start, wb_end) != (start.isoformat(), end.isoformat()):
            raise ReportError(f'The workbook period is {wb_start} to {wb_end} but you entered {start} to {end}.')
        _ids, names = product_lookup(db)
        for name, val in move.items():
            units = Decimal(str(val.get('sold') or 0))
            if units == 0:
                continue
            owners = names.get(name.strip().casefold(), set())
            rows.append(dict(channel=channel, item_key=name, name=name,
                             product_id=next(iter(owners)) if len(owners) == 1 else None,
                             units_sold=d(units), sales_amount=None, currency=None))
        if not rows:
            raise ReportError('No clinic sales found in this movement report.')
        warnings.append('Clinic figures are units only. No prices or inventory are used.')
    if len({r['item_key'] for r in rows}) != len(rows):
        raise ReportError('Duplicate product identities in the file.')
    meta = dict(channel=channel, channel_label=CHANNEL_LABEL[channel], rows=len(rows),
                units=d(sum(Decimal(r['units_sold']) for r in rows)),
                revenue=None if channel == 'clinic' else d(sum(Decimal(r['sales_amount']) for r in rows)),
                currency=CHANNEL_CURRENCY[channel],
                unmapped_rows=sum(1 for r in rows if r['product_id'] is None))
    return rows, meta, warnings


def find_overlaps(db, channel, start, end):
    found = (db.table('weekly_sales_imports')
             .select('id,period_start,period_end,original_filename')
             .eq('channel', channel).lte('period_start', end.isoformat()).gte('period_end', start.isoformat())
             .execute().data or [])
    return found


def read_request():
    """Validate the form and parse the uploaded workbook. Returns everything needed to preview or save."""
    uploaded = request.files.get('file')
    if not uploaded or not uploaded.filename:
        raise ReportError('Choose an XLSX file.')
    if Path(uploaded.filename).suffix.lower() != '.xlsx':
        raise ReportError('Only original XLSX reports are supported.')
    start = parse_date(request.form.get('period_start'), 'Start date')
    end = parse_date(request.form.get('period_end'), 'End date')
    check_period(start, end)
    name = secure_filename(uploaded.filename)[:180]
    chosen = request.form.get('kind', 'auto')
    with tempfile.TemporaryDirectory(prefix='firstwell_weekly_') as folder:
        path = Path(folder) / name
        uploaded.save(path)
        if path.stat().st_size > 35 * 1024 * 1024:
            raise ReportError('Maximum file size is 35 MB.')
        raw_kind = detect_kind(path, name, chosen if chosen in KIND_CHANNEL else 'auto')
        if raw_kind not in KIND_CHANNEL:
            raise ReportError('Weekly sales accepts only Shopee MY sales, Shopee SG sales and Clinic movement files.')
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        db = client()
        rows, meta, warnings = parse_report(path, name, raw_kind, start, end, db)
    return dict(db=db, kind=raw_kind, name=name, start=start, end=end, sha=sha, rows=rows, meta=meta, warnings=warnings)


@bp.post('/preview')
def preview():
    try:
        r = read_request()
        db = r['db']
        overlaps = find_overlaps(db, r['meta']['channel'], r['start'], r['end'])
        same = db.table('weekly_sales_imports').select('id,period_start,period_end').eq('sha256', r['sha']).limit(1).execute().data or []
        conflicts = [f"Overlaps an earlier {r['meta']['channel_label']} import ({o['period_start']} to {o['period_end']}, {o['original_filename']})." for o in overlaps if o['id'] not in {x['id'] for x in same}]
        already = bool(same)
        return jsonify(ok=True, kind=r['kind'], period_start=r['start'].isoformat(), period_end=r['end'].isoformat(),
                       sha256=r['sha'], metrics=r['meta'], warnings=r['warnings'], conflicts=conflicts,
                       already_imported=already, can_accept=(not conflicts) and (not already))
    except ReportError as exc:
        return jsonify(error=str(exc)), 400
    except Exception as exc:
        LOG.exception('Weekly sales preview failed')
        return jsonify(error='Preview failed: ' + str(exc)), 400


@bp.post('/accept')
def accept():
    import_id = None
    db = None
    try:
        r = read_request()
        db = r['db']
        if request.form.get('expected_sha256') != r['sha']:
            raise ReportError('This is not the file that was previewed. Preview it again.')
        if db.table('weekly_sales_imports').select('id').eq('sha256', r['sha']).limit(1).execute().data:
            return jsonify(ok=True, inserted=0, message='This exact file was already imported. Nothing was added.')
        overlaps = find_overlaps(db, r['meta']['channel'], r['start'], r['end'])
        if overlaps:
            raise ReportError('This period overlaps an earlier import for the same channel. Nothing was saved.')
        staff = getattr(g, 'staff', None) or {}
        created = db.table('weekly_sales_imports').insert(dict(
            channel=r['meta']['channel'], period_start=r['start'].isoformat(), period_end=r['end'].isoformat(),
            original_filename=r['name'], sha256=r['sha'], row_count=len(r['rows']),
            imported_by=staff.get('email'))).execute().data
        import_id = created[0]['id']
        for i in range(0, len(r['rows']), 200):
            batch = [dict(x, import_id=import_id) for x in r['rows'][i:i + 200]]
            db.table('weekly_sales_rows').insert(batch).execute()
        return jsonify(ok=True, inserted=len(r['rows']),
                       message=f"Saved {len(r['rows'])} rows for {r['meta']['channel_label']} {r['start']} to {r['end']}.")
    except ReportError as exc:
        return jsonify(error=str(exc)), 400
    except Exception:
        LOG.exception('Weekly sales import failed')
        if db is not None and import_id:  # remove only the import this request created (rows cascade)
            try:
                db.table('weekly_sales_imports').delete().eq('id', import_id).execute()
            except Exception:
                LOG.exception('Cleanup of the incomplete weekly import failed')
        return jsonify(error='The import failed and was rolled back. Nothing was saved. Check the server log.'), 503


def gaps_in(periods, lo, hi):
    """Date spans inside [lo, hi] not covered by any (start, end) period."""
    gaps, cursor = [], lo
    for s, e in sorted(periods):
        if s > cursor:
            gaps.append((cursor, min(s - dt.timedelta(days=1), hi)))
        cursor = max(cursor, e + dt.timedelta(days=1))
        if cursor > hi:
            break
    if cursor <= hi:
        gaps.append((cursor, hi))
    return [(a, b) for a, b in gaps if a <= b]


def summary_data(db, lo=None, hi=None):
    imports = fetch_pages(lambda: db.table('weekly_sales_imports')
                          .select('id,channel,period_start,period_end,original_filename,row_count,imported_at')
                          .order('period_start').order('id'))
    if not imports:
        return dict(imports=[], range=None, totals=[], weeks=[], gaps={}, top_products={}, notes=[])
    for i in imports:
        i['start'], i['end'] = dt.date.fromisoformat(i['period_start']), dt.date.fromisoformat(i['period_end'])
    lo = lo or min(i['start'] for i in imports)
    hi = hi or max(i['end'] for i in imports)
    inside = [i for i in imports if i['start'] >= lo and i['end'] <= hi]
    partial = [i for i in imports if (i['start'] <= hi and i['end'] >= lo) and i not in inside]
    ids = [i['id'] for i in inside]
    rows = []
    for k in range(0, len(ids), 40):
        chunk = ids[k:k + 40]
        rows += fetch_pages(lambda c=chunk: db.table('weekly_sales_rows')
                            .select('import_id,channel,item_key,name,product_id,units_sold,sales_amount,currency')
                            .in_('import_id', c).order('id'))
    by_import = defaultdict(lambda: dict(units=Decimal(0), revenue=Decimal(0), rows=0, unmapped=0))
    products = defaultdict(lambda: dict(name='', units=Decimal(0), revenue=Decimal(0)))
    for r in rows:
        agg = by_import[r['import_id']]
        agg['units'] += Decimal(str(r['units_sold']))
        agg['rows'] += 1
        if r['sales_amount'] is not None:
            agg['revenue'] += Decimal(str(r['sales_amount']))
        if r['product_id'] is None:
            agg['unmapped'] += 1
        p = products[(r['channel'], r['item_key'])]
        p['name'] = r['name'] or r['item_key']
        p['units'] += Decimal(str(r['units_sold']))
        if r['sales_amount'] is not None:
            p['revenue'] += Decimal(str(r['sales_amount']))
    weeks, totals = [], {}
    for i in inside:
        a = by_import[i['id']]
        cur = CHANNEL_CURRENCY[i['channel']]
        weeks.append(dict(channel=i['channel'], channel_label=CHANNEL_LABEL[i['channel']], period_start=i['period_start'],
                          period_end=i['period_end'], units=float(a['units']),
                          revenue=None if cur is None else float(a['revenue']), currency=cur,
                          rows=a['rows'], unmapped_rows=a['unmapped'], file=i['original_filename']))
        t = totals.setdefault(i['channel'], dict(channel=i['channel'], channel_label=CHANNEL_LABEL[i['channel']],
                                                 currency=cur, units=Decimal(0), revenue=Decimal(0), periods=0, days=0))
        t['units'] += a['units']
        t['revenue'] += a['revenue']
        t['periods'] += 1
        t['days'] += (i['end'] - i['start']).days + 1
    out_totals = [dict(t, units=float(t['units']), revenue=None if t['currency'] is None else float(t['revenue']))
                  for t in totals.values()]
    top = {}
    for ch in CHANNEL_LABEL:
        items = sorted(((k[1], v) for k, v in products.items() if k[0] == ch), key=lambda kv: kv[1]['units'], reverse=True)[:15]
        top[ch] = [dict(name=v['name'], units=float(v['units']),
                        revenue=None if CHANNEL_CURRENCY[ch] is None else float(v['revenue'])) for _k, v in items]
    gaps = {}
    for ch in CHANNEL_LABEL:
        spans = [(i['start'], i['end']) for i in inside if i['channel'] == ch]
        if spans or any(t['channel'] == ch for t in out_totals):
            gaps[ch] = [(a.isoformat(), b.isoformat()) for a, b in gaps_in(spans, lo, hi)]
    notes = ['Only whole uploads that lie fully inside the selected dates are counted.',
             'Shopee MY is in MYR and Shopee SG is in SGD. They are never added together.',
             'Clinic figures are units only.']
    if partial:
        notes.append(f'{len(partial)} upload(s) overlap the range edges and are not counted: ' +
                     ', '.join(f"{p['period_start']} to {p['period_end']}" for p in partial))
    weeks.sort(key=lambda w: (w['period_start'], w['channel']))
    return dict(range=dict(start=lo.isoformat(), end=hi.isoformat()),
                imports=[{k: v for k, v in i.items() if k not in ('start', 'end')} for i in imports],
                totals=out_totals, weeks=weeks, gaps=gaps, top_products=top, notes=notes)


@bp.get('/summary')
def summary():
    try:
        lo = parse_date(request.args['from'], 'From') if request.args.get('from') else None
        hi = parse_date(request.args['to'], 'To') if request.args.get('to') else None
        if lo and hi and hi < lo:
            raise ReportError('The end date is before the start date.')
        return jsonify(ok=True, **summary_data(client(), lo, hi))
    except ReportError as exc:
        return jsonify(error=str(exc)), 400
    except Exception:
        LOG.exception('Weekly sales summary failed')
        return jsonify(error='Could not load weekly sales.'), 503


def register_weekly_sales_api(app):
    app.register_blueprint(bp)
