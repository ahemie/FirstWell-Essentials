"""Read-only reference to FirstStep's Avixo, kept in FirstStep's own Supabase project.

FirstWell sells some products whose stock is kept in FirstStep's Avixo. Stock After Sales uses this list to find
sales that are not in FirstWell's Avixo report, and shows them as a separate "deduct from FirstStep's Avixo" table.

Only SELECT queries are made here; nothing is ever written to FirstStep's database.
Configure in .env / Vercel (leave empty to switch the feature off):
  FIRSTSTEP_SUPABASE_URL=https://<firststep-project>.supabase.co
  FIRSTSTEP_SUPABASE_KEY=<FirstStep secret / service_role key>   (server only, never sent to the browser)
Stock is the latest Avixo Inventory Report uploaded to FirstStep's dashboard (monthly), so it can be a few weeks old.
"""
import datetime as dt
import logging
import os
import threading
import time

LOG = logging.getLogger(__name__)
LABEL = "FirstStep's Avixo"
_cache = {'at': 0.0, 'data': None}
_lock = threading.Lock()
TTL = 300  # seconds


def configured():
    return bool(os.environ.get('FIRSTSTEP_SUPABASE_URL') and os.environ.get('FIRSTSTEP_SUPABASE_KEY'))


def _pages(query, size=1000):
    out, start = [], 0
    while True:
        part = query().range(start, start + size - 1).execute().data or []
        out += part
        if len(part) < size:
            return out
        start += size


def _load():
    from supabase import create_client
    db = create_client(os.environ['FIRSTSTEP_SUPABASE_URL'], os.environ['FIRSTSTEP_SUPABASE_KEY'])
    latest = db.table('inventory_snapshots').select('snapshot_date').order('snapshot_date', desc=True).limit(1).execute().data
    snap = latest[0]['snapshot_date'] if latest else None
    prods = _pages(lambda: db.table('products').select('id,avixo_id,name,stock_unit').order('avixo_id'))
    qty, batches = {}, {}
    if snap:
        for r in _pages(lambda: db.table('inventory_snapshots').select('product_id,quantity').eq('snapshot_date', snap).order('product_id')):
            qty[r['product_id']] = float(r['quantity'] or 0)
        for r in _pages(lambda: db.table('inventory_batches').select('product_id,expiry_date,quantity,batch_number')
                        .eq('snapshot_date', snap).order('product_id').order('batch_number')):
            e = r.get('expiry_date')
            e = dt.date.fromisoformat(e).strftime('%d/%m/%Y') if e else ''
            batches.setdefault(r['product_id'], []).append((e, float(r['quantity'] or 0)))
    products = []
    for p in prods:
        aid = str(p['avixo_id']).strip()
        products.append(dict(id=int(aid) if aid.isdigit() else aid, name=p['name'], unit=p.get('stock_unit') or '',
                             balance=qty.get(p['id'], 0.0), batches=batches.get(p['id'], [])))
    when = dt.date.fromisoformat(snap).strftime('%d/%m/%Y') if snap else 'no stock uploaded'
    return dict(label=LABEL, when=when, products=products)


def load_reference(notes=None):
    """FirstStep's Avixo products with stock, or None when not configured / unreachable (a note explains why)."""
    if not configured():
        return None
    with _lock:
        if _cache['data'] is not None and time.time() - _cache['at'] < TTL:
            return _cache['data']
        try:
            data = _load()
        except Exception as exc:
            LOG.exception("Could not read FirstStep's Avixo")
            if notes is not None:
                notes.append(f"Could not read FirstStep's Avixo from its Supabase ({type(exc).__name__}). "
                             'Check FIRSTSTEP_SUPABASE_URL / FIRSTSTEP_SUPABASE_KEY in .env.')
            return None
        _cache.update(at=time.time(), data=data)
        return data
