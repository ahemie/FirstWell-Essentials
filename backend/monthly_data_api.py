"""Read-only monthly Supabase data for older Inventory/Analytics/Product pages.

Uses source-month sales rows and that month's own month-end inventory snapshot (if uploaded).
Never pretends a later snapshot's stock or prices were valid during an earlier sales month.
All endpoints are subject to the application's existing staff-login guard.
"""
import datetime as dt
import logging
import re
from collections import defaultdict
from decimal import Decimal, InvalidOperation

from flask import Blueprint, jsonify, request
from backend.supabase_upload import client, fetch_all

log = logging.getLogger(__name__)
bp = Blueprint('monthly_data_api', __name__, url_prefix='/api/monthly')
MONTH_PATTERN = re.compile(r'^20\d\d-(0[1-9]|1[0-2])$')


def number(value):
    if value is None:
        return None
    try:
        return float(Decimal(str(value)))
    except (InvalidOperation, ValueError, TypeError):
        return None


def label(month):
    date = dt.date.fromisoformat(month + '-01')
    return date.strftime('%b %Y')


def months_data(db):
    rows = fetch_all(db, 'v_channel_monthly_summary',
                     'report_month,channel', sort='report_month')
    months = sorted({r['report_month'][:7] for r in rows if r.get('report_month')}, reverse=True)
    return [{'key': m, 'label': label(m)} for m in months]


def month_snapshot_date(db, month):
    """Month-end inventory snapshot for the selected report month, or None.

    The uploader only accepts an Avixo inventory report dated the last day of the month
    or the day after (e.g. 2026-07-31 or 2026-08-01 for July). Later snapshots are never
    used for an earlier month.
    """
    first = dt.date.fromisoformat(month + '-01')
    last = (first.replace(day=28) + dt.timedelta(days=4)).replace(day=1) - dt.timedelta(days=1)
    wanted = [last.isoformat(), (last + dt.timedelta(days=1)).isoformat()]
    rows = (db.table('inventory_snapshots').select('snapshot_date')
            .in_('snapshot_date', wanted).order('snapshot_date', desc=True).limit(1).execute().data or [])
    return rows[0]['snapshot_date'] if rows else None


def detail_data(db, month):
    if not MONTH_PATTERN.fullmatch(month):
        raise ValueError('Choose a valid month in YYYY-MM format')
    month_date = month + '-01'
    monthly = fetch_all(db, 'v_channel_monthly_summary',
                        'report_month,channel,currency,units_sold,revenue,revenue_basis,unmatched_rows',
                        {'report_month': month_date}, sort='channel')
    if not monthly:
        return None

    products = fetch_all(db, 'products', 'id,avixo_id,name,category', sort='avixo_id')
    by_id = {}
    for p in products:
        by_id[p['id']] = {
            'product_id': p['id'], 'avixo_id': p.get('avixo_id'),
            'name': p.get('name') or 'Unnamed product',
            'category': p.get('category') or 'Uncategorised',
            'stock_quantity': None, 'clinic_price_rm': None,
            'stock_value_rm': None, 'latest_cost_rm': None,
            'clinic_sold': 0, 'clinic_estimated_revenue_rm': None,
            'my_sold': 0, 'my_revenue_myr': 0,
            'sg_sold': 0, 'sg_revenue_sgd': 0,
        }

    # Stock, cost and Clinic price come ONLY from this month's own month-end snapshot.
    snapshot_date = month_snapshot_date(db, month)
    if snapshot_date:
        stock_rows = fetch_all(db, 'inventory_snapshots',
                               'product_id,quantity,clinic_list_price_rm,stock_value_rm,latest_cost_rm',
                               {'snapshot_date': snapshot_date}, sort='product_id')
        for s in stock_rows:
            item = by_id.get(s['product_id'])
            if item:
                item['stock_quantity'] = number(s.get('quantity'))
                item['stock_value_rm'] = number(s.get('stock_value_rm'))
                item['clinic_price_rm'] = number(s.get('clinic_list_price_rm'))
                item['latest_cost_rm'] = number(s.get('latest_cost_rm'))

    clinic = fetch_all(db, 'clinic_movement_monthly',
                       'product_id,avixo_name_in_report,units_sold,estimated_revenue_rm,price_snapshot_date',
                       {'report_month': month_date}, sort='id')
    clinic_unmapped = []
    price_dates = set()
    for r in clinic:
        item = by_id.get(r.get('product_id'))
        if not item:
            clinic_unmapped.append({
                'name': r.get('avixo_name_in_report') or 'Unmatched Clinic item',
                'units': number(r.get('units_sold')),
            })
            continue
        item['clinic_sold'] += number(r.get('units_sold')) or 0
        amount = number(r.get('estimated_revenue_rm'))
        if amount is not None:
            item['clinic_estimated_revenue_rm'] = (item['clinic_estimated_revenue_rm'] or 0) + amount
        if r.get('price_snapshot_date'):
            price_dates.add(r['price_snapshot_date'])

    # Cleaned view avoids adding parent and variation sales twice.
    sales = fetch_all(db, 'v_shopee_sales_clean',
                      'marketplace,product_id,shopee_item_id,shopee_variation_id,units_sold,sales_amount,currency',
                      {'report_month': month_date}, sort='shopee_item_id')
    shopee_unmapped = defaultdict(lambda: {'marketplace': None, 'shopee_item_id': None, 'units': 0, 'revenue': 0})
    for row in sales:
        market = row.get('marketplace')
        if market not in ('MY','SG'):
            continue
        qty = number(row.get('units_sold')) or 0
        revenue = number(row.get('sales_amount')) or 0
        item = by_id.get(row.get('product_id'))
        if item is None:
            key = (market, row.get('shopee_item_id'))
            entry = shopee_unmapped[key]
            entry['marketplace'] = market
            entry['shopee_item_id'] = row.get('shopee_item_id')
            entry['units'] += qty
            entry['revenue'] += revenue
            continue
        if market == 'MY':
            item['my_sold'] += qty
            item['my_revenue_myr'] += revenue
        else:
            item['sg_sold'] += qty
            item['sg_revenue_sgd'] += revenue

    return {
        'source': 'supabase',
        'month': month,
        'month_label': label(month),
        'monthly': monthly,
        'snapshot_date': snapshot_date,
        'clinic_price_reference_dates': sorted(price_dates),
        'products': list(by_id.values()),
        'unmapped_shopee': list(shopee_unmapped.values()),
        'unmapped_clinic': clinic_unmapped,
        'notes': [
            'Sales and movement quantities are from the selected report month.',
            'Stock, cost and Clinic list price come from this month\'s own month-end inventory snapshot. Without one, they are shown as No data.',
            'Clinic revenue is an estimate, not confirmed receipts.',
            'Shopee MY revenue is MYR and Shopee SG revenue is SGD. Never add or directly compare currencies.',
            'Unmapped Shopee listings are excluded from verified Avixo product rows but remain in monthly channel totals.',
            'No historical MTD/day-level information is inferred from monthly reports.',
        ],
    }


CHANNEL_KEY = {'Clinic': 'clinic', 'Shopee MY': 'my', 'Shopee SG': 'sg'}


def build_trends(summary_rows, clinic_rows, sales_rows, products):
    """Per-product monthly history for the Product Details trends, in the shape of data/product_trends.json.

    products[avixo_id][YYYY-MM][clinic|my|sg] = {units, revenue}. A channel that had a report in a month but no
    rows for the product counts as 0 sold; a channel with no report that month is None (shown as a gap, never zero).
    Shopee MY is MYR and Shopee SG is SGD; nothing is converted. Clinic revenue is the stored estimate.
    """
    reported = {'clinic': set(), 'my': set(), 'sg': set()}
    for row in summary_rows:
        key = CHANNEL_KEY.get(row.get('channel'))
        if key and row.get('report_month'):
            reported[key].add(row['report_month'][:7])
    months = sorted(set().union(*reported.values()))
    avixo_by_id = {p['id']: str(p['avixo_id']) for p in products if p.get('avixo_id') is not None}

    totals = {}   # (avixo, month, channel) -> [units, revenue]

    def add(avixo, month, channel, units, revenue):
        cell = totals.setdefault((avixo, month, channel), [0.0, 0.0])
        cell[0] += units or 0
        cell[1] += revenue or 0

    for r in clinic_rows:
        avixo = avixo_by_id.get(r.get('product_id'))
        if avixo and r.get('report_month'):
            add(avixo, r['report_month'][:7], 'clinic', number(r.get('units_sold')), number(r.get('estimated_revenue_rm')))
    for r in sales_rows:
        avixo = avixo_by_id.get(r.get('product_id'))
        channel = {'MY': 'my', 'SG': 'sg'}.get(r.get('marketplace'))
        if avixo and channel and r.get('report_month'):
            add(avixo, r['report_month'][:7], channel, number(r.get('units_sold')), number(r.get('sales_amount')))

    result = {}
    for avixo in avixo_by_id.values():
        history = {}
        for month in months:
            entry = {}
            for channel in ('clinic', 'my', 'sg'):
                if month in reported[channel]:
                    units, revenue = totals.get((avixo, month, channel), (0.0, 0.0))
                    entry[channel] = {'units': units, 'revenue': round(revenue, 2)}
                else:
                    entry[channel] = {'units': None, 'revenue': None}
            history[month] = entry
        result[avixo] = history
    return {'meta': {'months': months, 'source': 'supabase', 'myCurrency': 'MYR', 'sgCurrency': 'SGD',
                     'clinicCurrency': 'MYR',
                     'note': 'Supabase monthly reports. Shopee revenue excludes platform fees. Clinic revenue is units x the '
                             'latest Avixo list price (an estimate, not a historical price). MYR and SGD are never converted.'},
            'products': result}


def _fetch_ordered(db, table, columns, orders, filters=None):
    """Page through a view with a stable, multi-column order (views have no single unique id)."""
    rows, start = [], 0
    while True:
        q = db.table(table).select(columns)
        for k, v in (filters or {}).items():
            q = q.eq(k, v)
        for column in orders:
            q = q.order(column)
        batch = q.range(start, start + 499).execute().data or []
        rows.extend(batch)
        if len(batch) < 500:
            return rows
        start += 500


def trends_data(db):
    summary = fetch_all(db, 'v_channel_monthly_summary', 'report_month,channel', sort='report_month')
    products = fetch_all(db, 'products', 'id,avixo_id', sort='avixo_id')
    clinic = fetch_all(db, 'clinic_movement_monthly', 'report_month,product_id,units_sold,estimated_revenue_rm', sort='id')
    sales = []
    for month in sorted({r['report_month'] for r in summary if r.get('report_month')}):
        for market in ('MY', 'SG'):
            sales += _fetch_ordered(db, 'v_shopee_sales_clean',
                                    'report_month,marketplace,product_id,units_sold,sales_amount',
                                    ['shopee_item_id', 'shopee_variation_id', 'sales_level'],
                                    {'report_month': month, 'marketplace': market})
    return build_trends(summary, clinic, sales, products)


@bp.get('/trends')
def trends():
    try:
        return jsonify(trends_data(client()))
    except Exception:
        log.exception('Unable to build product trends from Supabase')
        return jsonify(error='Could not read product trends from Supabase'), 503


@bp.get('/fees')
def fees():
    """Shopee payout settings (keep % and voucher per unit), effective-dated, edited in Supabase table channel_fee_rates."""
    try:
        rows = fetch_all(client(), 'channel_fee_rates', 'marketplace,effective_from,keep_pct,voucher_per_unit,note', sort='effective_from')
        return jsonify(rates=[{'marketplace': r['marketplace'], 'effective_from': r['effective_from'],
                               'keep_pct': float(r['keep_pct']), 'voucher_per_unit': float(r['voucher_per_unit'] or 0),
                               'note': r.get('note')} for r in rows])
    except Exception:
        log.exception('Unable to read channel fee rates from Supabase')
        return jsonify(error='Could not read channel fee rates from Supabase'), 503


@bp.get('/months')
def months():
    try:
        return jsonify(source='supabase', months=months_data(client()))
    except Exception:
        log.exception('Cannot read reporting months')
        return jsonify(error='Could not read monthly reports from Supabase'), 503


@bp.get('/detail')
def detail():
    month = (request.args.get('month') or '').strip()
    if not MONTH_PATTERN.fullmatch(month):
        return jsonify(error='Invalid reporting month'), 400
    try:
        payload = detail_data(client(), month)
        if payload is None:
            return jsonify(error='No saved sales or Clinic report for this month'), 404
        return jsonify(payload)
    except Exception:
        log.exception('Cannot read monthly data')
        return jsonify(error='Could not read monthly data from Supabase'), 503


def register_monthly_data_api(app):
    app.register_blueprint(bp)
