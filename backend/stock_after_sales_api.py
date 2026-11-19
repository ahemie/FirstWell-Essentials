"""Staff-only "Stock after sales": the chosen inventory snapshot minus the weekly sales uploads.

  opening stock  = quantity in inventory_snapshots for the chosen snapshot date
  sold           = units in weekly_sales_rows (Shopee MY, Shopee SG, Clinic) from whole uploads whose period
                   lies inside [from, to]; uploads that only partly overlap are listed and NOT counted
  stock after    = opening - sold  (can go below zero; those rows are flagged)
Nothing is written to the database.

Route (behind the app's staff login):
  GET /api/stock-after-sales   ?snapshot=YYYY-MM-DD  &from=YYYY-MM-DD  &to=YYYY-MM-DD   (all optional)
"""
import datetime as dt
import hashlib
import logging
import re
import uuid
from collections import defaultdict
from decimal import Decimal

import tempfile
from pathlib import Path

from flask import Blueprint, jsonify, request
from werkzeug.utils import secure_filename

from backend.supabase_upload import client
from backend.weekly_sales_api import CHANNEL_LABEL, ReportError, fetch_pages, parse_date

bp = Blueprint('stock_after_sales_api', __name__, url_prefix='/api/stock-after-sales')
LOG = logging.getLogger(__name__)
CHANNELS = list(CHANNEL_LABEL)  # shopee_my, shopee_sg, clinic


def dec(v):
    return Decimal(str(v if v is not None else 0))


def compute(opening, products, sales):
    """opening: [{product_id, quantity}], products: {id: {name, unit, category}},
    sales: [{channel, product_id, item_key, name, units_sold}]. Returns (rows, unmatched)."""
    base = {o['product_id']: dec(o['quantity']) for o in opening}
    sold = defaultdict(lambda: {c: Decimal(0) for c in CHANNELS})
    unmatched = defaultdict(lambda: Decimal(0))
    for s in sales:
        u = dec(s['units_sold'])
        if s.get('product_id'):
            sold[s['product_id']][s['channel']] += u
        else:
            unmatched[(s['channel'], s.get('item_key') or '', s.get('name') or '')] += u
    rows = []
    for pid in set(base) | set(sold):
        p = products.get(pid, {})
        by = sold.get(pid, {c: Decimal(0) for c in CHANNELS})
        total = sum(by.values(), Decimal(0))
        open_q = base.get(pid, Decimal(0))
        rows.append(dict(product_id=pid, name=p.get('name') or '(unknown product)', unit=p.get('unit') or '',
                         category=p.get('category') or '', opening=float(open_q),
                         sold={c: float(by[c]) for c in CHANNELS}, sold_total=float(total),
                         after=float(open_q - total), in_snapshot=pid in base))
    rows.sort(key=lambda r: (r['after'] >= 0, r['name'].casefold()))
    un = [dict(channel=k[0], channel_label=CHANNEL_LABEL[k[0]], item_key=k[1], name=k[2] or k[1], units=float(v))
          for k, v in unmatched.items() if v]
    un.sort(key=lambda x: -x['units'])
    return rows, un


def build(db, snapshot=None, lo=None, hi=None):
    snaps = sorted({r['snapshot_date'] for r in fetch_pages(lambda: db.table('inventory_snapshots').select('snapshot_date').order('snapshot_date'))}, reverse=True)
    if not snaps:
        raise ReportError('No inventory has been uploaded yet.')
    snap = snapshot or snaps[0]
    if snap not in snaps:
        raise ReportError('That inventory date does not exist.')
    imports = fetch_pages(lambda: db.table('weekly_sales_imports')
                          .select('id,channel,period_start,period_end,original_filename').order('period_start').order('id'))
    lo = lo or dt.date.fromisoformat(snap)
    after_lo = [i for i in imports if dt.date.fromisoformat(i['period_end']) >= lo]
    hi = hi or (max((dt.date.fromisoformat(i['period_end']) for i in after_lo), default=lo))
    inside = [i for i in after_lo if dt.date.fromisoformat(i['period_start']) >= lo and dt.date.fromisoformat(i['period_end']) <= hi]
    skipped = [i for i in after_lo if i not in inside and dt.date.fromisoformat(i['period_start']) <= hi]
    opening = fetch_pages(lambda: db.table('inventory_snapshots').select('product_id,quantity').eq('snapshot_date', snap).order('product_id'))
    prods = {p['id']: dict(name=p['name'], unit=p.get('stock_unit'), category=p.get('category'))
             for p in fetch_pages(lambda: db.table('products').select('id,name,stock_unit,category').order('id'))}
    sales = []
    ids = [i['id'] for i in inside]
    for k in range(0, len(ids), 40):
        chunk = ids[k:k + 40]
        sales += fetch_pages(lambda c=chunk: db.table('weekly_sales_rows')
                             .select('channel,item_key,name,product_id,units_sold').in_('import_id', c).order('id'))
    rows, unmatched = compute(opening, prods, sales)
    return dict(snapshots=snaps, snapshot=snap, range=dict(start=lo.isoformat(), end=hi.isoformat()),
                counted=[dict(channel=i['channel'], channel_label=CHANNEL_LABEL[i['channel']], period_start=i['period_start'],
                              period_end=i['period_end'], file=i['original_filename']) for i in inside],
                skipped=[dict(channel_label=CHANNEL_LABEL[i['channel']], period_start=i['period_start'], period_end=i['period_end']) for i in skipped],
                channels=[dict(id=c, label=CHANNEL_LABEL[c]) for c in CHANNELS],
                rows=rows, unmatched=unmatched)


@bp.get('')
def stock_after_sales():
    try:
        lo = parse_date(request.args['from'], 'From') if request.args.get('from') else None
        hi = parse_date(request.args['to'], 'To') if request.args.get('to') else None
        if lo and hi and hi < lo:
            raise ReportError('The end date is before the start date.')
        return jsonify(ok=True, **build(client(), request.args.get('snapshot') or None, lo, hi))
    except ReportError as exc:
        return jsonify(error=str(exc)), 400
    except Exception:
        LOG.exception('Stock after sales failed')
        return jsonify(error='Could not calculate stock after sales.'), 503


def read_uploads(sc):
    """Reads the uploaded files, one per box (inventory, shopee_my, shopee_sg, tiktok).
    Returns (parsed, file_infos); file_infos carry each file's sha256."""
    parsed, infos = [], []
    with tempfile.TemporaryDirectory(prefix='firstwell_stock_') as folder:
        for slot, label in sc.SLOTS:
            f = request.files.get(slot)
            if not f or not f.filename:
                continue
            name = secure_filename(f.filename)[:150] or slot
            path = Path(folder) / f'{slot}_{name}'
            f.save(path)
            if path.stat().st_size > 12 * 1024 * 1024:
                raise sc.FileError(f'{name}: files can be at most 12 MB.')
            grid = sc.read_grid(path, name)
            parsed.append((slot, f.filename[:150], grid))
            infos.append(dict(slot=slot, name=f.filename[:150], sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    if not any(i['slot'] == 'inventory' for i in infos):
        raise sc.FileError('Choose the Avixo Inventory Report in the Inventory box.')
    if len(infos) < 2:
        raise sc.FileError('Choose at least one sales file (Shopee or TikTok).')
    return parsed, infos


def combined_sha(infos):
    return hashlib.sha256('|'.join(sorted(i['slot'] + ':' + i['sha256'] for i in infos)).encode()).hexdigest()


def sales_infos(infos):
    return [dict(sha256=i['sha256'], name=i['name'], kind=i['slot']) for i in infos if i['slot'] != 'inventory']


@bp.post('/from-files')
def from_files():
    """Preview: upload the Avixo Inventory Report + platform sales files. Nothing is saved and no stock is changed."""
    from backend import stock_files_calc as sc
    try:
        parsed, infos = read_uploads(sc)
        result = sc.calculate(parsed)
        sales = sales_infos(infos)
        saved = []
        if sales:
            hit = client().table('inv_sales_applied_files').select('sha256,file_name,applied_at').in_('sha256', [i['sha256'] for i in sales]).execute().data or []
            saved = [dict(file=h['file_name'], at=h['applied_at']) for h in hit]
        result.update(sha256=combined_sha(infos), already_saved=saved, can_save=bool(result['rows']) and not saved)
        return jsonify(ok=True, **result)
    except sc.FileError as exc:
        return jsonify(error=str(exc)), 400
    except Exception:
        LOG.exception('Stock from files failed')
        return jsonify(error='Could not read these files. Upload the original exports without editing them.'), 400


@bp.post('/save')
def save_history():
    """Save the calculation as history only. It does not change any stock."""
    from backend import stock_files_calc as sc
    from flask import g
    try:
        parsed, infos = read_uploads(sc)
        if request.form.get('expected_sha256') != combined_sha(infos):
            raise sc.FileError('The files changed since the preview. Preview again before saving.')
        date_iso = (request.form.get('sales_date') or '').strip()
        try:
            dt.date.fromisoformat(date_iso)
        except ValueError:
            raise sc.FileError('Choose the sales date.')
        result = sc.calculate(parsed)
        lines = [dict(avixo_id=str(r['id']), name=r['name'], channel=sc.LABEL[c], qty=q, avixo_before=r['before'], avixo_after=r['after'],
                      remark=sc.make_remark(r['sold'], date_iso, result['slot_dates'] if date_iso == result['sales_date'] else None))
                 for r in result['rows'] for c, q in r['sold'].items() if q > 0]
        sales = sales_infos(infos)
        if not lines or not sales:
            raise sc.FileError('There is nothing to save.')
        try:
            res = client().rpc('inv_sales_record', {'p_staff': g.staff['email'], 'p_files': sales, 'p_lines': lines,
                                                    'p_meta': {'file': result['inventory']['file'], 'when': result['inventory']['when'], 'sales_date': date_iso}}).execute().data
        except Exception as exc:
            m = re.search(r'ALREADY_SAVED\|([^"\\]+)', str(exc))
            if m:
                raise sc.FileError(f'{m.group(1)} was already saved in the history.')
            raise
        res = dict(res, ok=True)
        return jsonify(**res)
    except sc.FileError as exc:
        return jsonify(error=str(exc)), 400
    except Exception:
        LOG.exception('Stock save failed')
        return jsonify(error='Could not save the history. Nothing was saved.'), 500


@bp.get('/history')
def history():
    """Confirmed uploads, newest first (what was applied, by whom, from which files)."""
    try:
        return jsonify(ok=True, items=client().rpc('inv_sales_history', {}).execute().data or [])
    except Exception:
        LOG.exception('Stock history failed')
        return jsonify(error='Could not load the history.'), 503


@bp.get('/history/<application_id>')
def history_detail(application_id):
    try:
        uuid.UUID(application_id)
    except ValueError:
        return jsonify(error='Unknown history entry.'), 400
    try:
        return jsonify(ok=True, lines=client().rpc('inv_sales_history', {'p_id': application_id}).execute().data or [])
    except Exception:
        LOG.exception('Stock history detail failed')
        return jsonify(error='Could not load this entry.'), 503


def register_stock_after_sales_api(app):
    app.register_blueprint(bp)
