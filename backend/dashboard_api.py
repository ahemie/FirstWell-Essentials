"""Staff-only read API that serves the processed monthly dashboard data from Supabase.

Returns the same shapes the original files had:
  /api/dashboard/months   -> [{"key","label","file"}, ...]   (like data/months.js)
  /api/dashboard/<YYYY-MM> -> {"meta": {...}, "products": [...]}  (like data/YYYY-MM.js)
Read-only. The service role key stays on the server.
"""
import logging
import re
from flask import Blueprint, jsonify

from backend.supabase_upload import client

bp = Blueprint('dashboard_api', __name__, url_prefix='/api/dashboard')
LOG = logging.getLogger(__name__)
MONTH_RE = re.compile(r'^\d{4}-\d{2}$')


@bp.get('/months')
def months():
    try:
        rows = client().table('dashboard_months').select('month_key,label').order('month_key').execute().data or []
        return jsonify([{'key': r['month_key'], 'label': r['label'], 'file': r['month_key'] + '.json'} for r in rows])
    except Exception:
        LOG.exception('Unable to list dashboard months')
        return jsonify(error='Could not load the month list from Supabase.'), 503


@bp.get('/<month>')
def month_data(month):
    if not MONTH_RE.match(month):
        return jsonify(error='Invalid month.'), 400
    try:
        rows = client().table('dashboard_months').select('meta,products').eq('month_key', month).execute().data
        if not rows:
            return jsonify(error='Month not found.'), 404
        return jsonify({'meta': rows[0]['meta'], 'products': rows[0]['products']})
    except Exception:
        LOG.exception('Unable to load dashboard month')
        return jsonify(error='Could not load that month from Supabase.'), 503


def register_dashboard_api(app):
    app.register_blueprint(bp)
