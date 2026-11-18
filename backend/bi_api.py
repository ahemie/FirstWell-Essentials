"""Staff-only read-only Supabase BI API for /bi.html.

No SQL schema changes and no writes. All access goes through the Flask server;
SUPABASE_SERVICE_ROLE_KEY never leaves the server. Data from the cleaned monthly
view is kept in its source currency and revenue basis.
"""
import logging
from collections import defaultdict
from decimal import Decimal
from flask import Blueprint, jsonify, request

from backend.supabase_upload import client, fetch_all

bp = Blueprint('bi_api', __name__, url_prefix='/api/bi')
LOG = logging.getLogger(__name__)


def as_float(value):
    try:
        return float(Decimal(str(value or 0)))
    except (ArithmeticError, ValueError, TypeError):
        return 0.0


def inventory_chart_data(stockrows, products_by_id, snapshot_date):
    """Aggregate latest stock snapshot for the BI chart cards (no live stock claim).

    Status is an informational quantity threshold: no stock <= 0,
    low stock 0 < quantity <= 5, available > 5. No arbitrary order advice.
    A value band uses each individual product's nonnegative stock value,
    not its unit price and not historical purchasing expenditure.
    """
    categories = defaultdict(lambda: {'out_of_stock': 0, 'low_stock': 0,
                                      'healthy': 0, 'unknown': 0})
    bands = [
        {'label': 'RM 0–500', 'count': 0, 'total_value_rm': 0.0},
        {'label': 'RM 501–2k', 'count': 0, 'total_value_rm': 0.0},
        {'label': 'RM 2k–5k', 'count': 0, 'total_value_rm': 0.0},
        {'label': 'Over RM 5k', 'count': 0, 'total_value_rm': 0.0},
    ]
    omitted_values = 0
    for row in stockrows:
        identity = products_by_id.get(row.get('product_id')) or {}
        category = (identity.get('category') or 'Uncategorised').strip() or 'Uncategorised'
        status = categories[category]
        qty = row.get('quantity')
        if qty is None:
            status['unknown'] += 1
        elif as_float(qty) <= 0:
            status['out_of_stock'] += 1
        elif as_float(qty) <= 5:
            status['low_stock'] += 1
        else:
            status['healthy'] += 1

        amount = row.get('stock_value_rm')
        if amount is None or as_float(amount) < 0:
            omitted_values += 1
            continue
        amount = as_float(amount)
        index = 0 if amount <= 500 else 1 if amount <= 2000 else 2 if amount <= 5000 else 3
        bands[index]['count'] += 1
        bands[index]['total_value_rm'] += amount

    ordered = sorted(categories.items(),
                     key=lambda pair: (-sum(pair[1].values()), pair[0].casefold()))
    displayed = []
    for name, counts in ordered[:5]:
        displayed.append({'name': name, **counts})
    if len(ordered) > 5:
        rest = {key: sum(counts[key] for _, counts in ordered[5:])
                for key in ('out_of_stock', 'low_stock', 'healthy', 'unknown')}
        displayed.append({'name': 'Other categories', **rest})
    for band in bands:
        band['total_value_rm'] = round(band['total_value_rm'], 2)
    return {
        'snapshot_date': snapshot_date,
        'categories': displayed,
        'value_bands': bands,
        'value_missing_or_negative_products': omitted_values,
        'stock_products_in_snapshot': len(stockrows),
    }


def shopee_listing_catalogue(links, prices, products_by_id, flags=None):
    """Every Shopee listing we know about, per marketplace, so the BI page can show which ones had no sales.

    Sources: product_channel_links (listing -> Avixo product) and the latest listing-price snapshot per
    marketplace (listings that exist on Shopee but are not linked to a product). Each product appears once
    per marketplace (several variations of one product count once). The key matches the BI sales grouping:
    `p:<avixo_id>` for linked products, `u:<item_id>` for unlinked listings. Unlinked listings flagged in
    `listing_flags` (free items) keep their readable name and carry `flag`.
    """
    out = {'MY': {}, 'SG': {}}
    flagged = {(f.get('marketplace'), str(f.get('shopee_item_id') or '')): f for f in (flags or [])}
    linked_items = {'MY': set(), 'SG': set()}
    for row in links:
        market = row.get('marketplace')
        if market not in out:
            continue
        product = products_by_id.get(row.get('product_id'))
        item = str(row.get('shopee_item_id') or '')
        if not product or not product.get('avixo_id'):
            continue
        linked_items[market].add(item)
        key = 'p:' + str(product['avixo_id'])
        out[market].setdefault(key, {'key': key, 'name': product.get('name') or 'Unnamed product',
                                     'avixo_id': product['avixo_id'], 'item_id': item, 'mapped': True})
    latest = {}
    for row in prices:
        market = row.get('marketplace')
        if market in out and (market not in latest or row['snapshot_date'] > latest[market]):
            latest[market] = row['snapshot_date']
    for row in prices:
        market = row.get('marketplace')
        if market not in out or row['snapshot_date'] != latest.get(market):
            continue
        item = str(row.get('shopee_item_id') or '')
        if item in linked_items[market]:
            continue
        key = 'u:' + item
        flag = flagged.get((market, item))
        if flag:
            out[market].setdefault(key, {'key': key, 'name': flag.get('display_name') or f'Free item {item}',
                                         'avixo_id': None, 'item_id': item, 'mapped': False,
                                         'flag': flag.get('flag') or 'free_item'})
            continue
        # FirstWell: a listing with no Avixo product link is left out (only Avixo products are listed).
    return {market: sorted(items.values(), key=lambda x: (x['name'].casefold(), x['key']))
            for market, items in out.items()}


def overview_data(db):
    monthly = fetch_all(
        db, 'v_channel_monthly_summary',
        'report_month,channel,currency,activity_rows,units_sold,revenue,matched_rows,unmatched_rows,revenue_basis',
        sort='report_month',
    )
    inventory = fetch_all(
        db, 'v_inventory_latest_summary',
        'snapshot_date,total_products,products_with_snapshot,total_stock_units,total_stock_value_rm,expiry_batch_rows',
        sort='snapshot_date',
    )
    # Details from the cleaned sales view; the view does not double-count
    # parent and variation sales. Do NOT add raw parent and variation tables.
    sales = fetch_all(
        db, 'v_shopee_sales_clean',
        'report_month,marketplace,shopee_item_id,shopee_variation_id,product_id,mapping_status,units_sold,sales_amount,currency,sales_level',
        sort='report_month',
    )
    products = fetch_all(db, 'products', 'id,avixo_id,name,category', sort='avixo_id')
    names = {p['id']: p for p in products}
    # Return compact detail rows and use the known names rather than assuming
    # every Shopee listing has a reliable Avixo mapping.
    detail = []
    for s in sales:
        p = names.get(s.get('product_id'))
        detail.append({
            'month': s['report_month'], 'marketplace': s['marketplace'],
            'item_id': s['shopee_item_id'], 'variation_id': s.get('shopee_variation_id') or '0',
            'name': p['name'] if p else f"Unmapped listing {s['shopee_item_id']}",
            'avixo_id': p['avixo_id'] if p else None,
            'mapped': bool(p),
            'units': as_float(s['units_sold']),
            'revenue': as_float(s['sales_amount']),
            'currency': s['currency'],
            'sales_level': s.get('sales_level'),
        })
    latest_stock = inventory[-1] if inventory else None
    # Stock value per snapshot date, so the page can show the month-end stock of the selected month.
    by_date = {}
    for r in fetch_all(db, 'inventory_snapshots', 'snapshot_date,quantity,stock_value_rm', sort='product_id'):
        d = str(r['snapshot_date'])
        a = by_date.setdefault(d, {'snapshot_date': d, 'products_with_snapshot': 0, 'total_stock_units': 0.0, 'total_stock_value_rm': 0.0})
        a['products_with_snapshot'] += 1
        a['total_stock_units'] += as_float(r.get('quantity'))
        a['total_stock_value_rm'] += as_float(r.get('stock_value_rm'))
    inventory_by_date = [by_date[k] for k in sorted(by_date)]
    stock_alerts = []
    stockrows = []
    if latest_stock:
        stockrows = fetch_all(db, 'inventory_snapshots',
                              'product_id,snapshot_date,quantity,latest_cost_rm,stock_value_rm',
                              {'snapshot_date': latest_stock['snapshot_date']}, sort='product_id')
        for s in stockrows:
            qty = as_float(s.get('quantity'))
            if s.get('quantity') is not None and qty <= 5:  # Missing is not zero stock.
                p = names.get(s.get('product_id'), {})
                stock_alerts.append({'avixo_id': p.get('avixo_id'), 'name': p.get('name') or 'Unknown product',
                                     'quantity': qty, 'stock_value_rm': as_float(s.get('stock_value_rm'))})
        stock_alerts.sort(key=lambda row: (row['quantity'], row['name']))
    inventory_charts = inventory_chart_data(
        stockrows, names, latest_stock['snapshot_date'] if latest_stock else None
    )
    prices = fetch_all(db, 'listing_price_snapshots',
                       'marketplace,shopee_item_id,shopee_variation_id,snapshot_date,listed_price,currency',
                       sort='snapshot_date')
    latest_dates = {}
    for p in prices:
        m = p['marketplace']
        if not latest_dates.get(m) or latest_dates[m] < p['snapshot_date']:
            latest_dates[m] = p['snapshot_date']
    prices_summary = {}
    for market, date in latest_dates.items():
        current = [p for p in prices if p['marketplace'] == market and p['snapshot_date'] == date]
        values = [as_float(p['listed_price']) for p in current]
        prices_summary[market] = {
            'date': date, 'currency': 'MYR' if market == 'MY' else 'SGD',
            'rows': len(current), 'items': len({p['shopee_item_id'] for p in current}),
            'min': min(values) if values else None,
            'max': max(values) if values else None,
        }
    links = fetch_all(db, 'product_channel_links',
                      'product_id,marketplace,shopee_item_id,shopee_variation_id', sort='id')
    try:
        flags = fetch_all(db, 'listing_flags', 'marketplace,shopee_item_id,flag,display_name', sort='shopee_item_id')
    except Exception:  # table not created yet: show listings as before
        flags = []
    listings = shopee_listing_catalogue(links, prices, names, flags)
    imports = fetch_all(db, 'report_imports',
                        'kind,reporting_month,snapshot_date,status,original_filename,imported_at',
                        sort='imported_at')
    return {
        'source': 'supabase',
        'months': sorted({m['report_month'][:7] for m in monthly}),
        'monthly': monthly,
        'inventory': latest_stock,
        'inventory_by_date': inventory_by_date,
        'inventory_charts': inventory_charts,
        'low_stock_threshold_units': 5,
        'low_stock_count': len(stock_alerts),
        'stock_alerts': stock_alerts[:50],
        'shopee_details': detail,
        'shopee_listings': listings,
        'listing_prices': prices_summary,
        'recent_imports': list(reversed(imports))[:12],
        'notes': [
            'Shopee sales are source report amounts. Clinic revenue is estimated, not actual receipts.',
            'MYR and SGD are never combined; no exchange rate is assumed.',
            'Latest inventory is a dated snapshot, not live stock.',
            'Inventory category counts use a 5-unit low-stock threshold, and value bands group per-product stock value.',
            'Top Shopee performers use cleaned sales view to avoid parent/variation double counting.',
            'Unmapped Shopee listings must not be treated as verified Avixo products.',
        ],
    }


@bp.get('/overview')
def overview():
    try:
        result = overview_data(client())
        return jsonify(ok=True, **result)
    except Exception:
        LOG.exception('Unable to calculate Supabase BI overview')
        return jsonify(error='Could not load Supabase BI. Check server logs and connection settings.'), 503


def register_bi_api(app):
    app.register_blueprint(bp)
