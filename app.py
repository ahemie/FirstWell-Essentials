# STAGING MIGRATION: Legacy SQLite report endpoints are disabled on Vercel.
"""FirstWell Essentials local monthly upload server. Start with: python app.py"""
import csv
import datetime as dt
import hashlib
import io
import json
import os
import re
import secrets
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from flask import Flask, jsonify, request, send_from_directory, redirect, make_response, g, url_for
from werkzeug.utils import secure_filename
from process_month import (open_workbook, read_inventory, read_movement,
                           read_shopee_price, read_shopee_perf)

ROOT = Path(__file__).resolve().parent
DB = ROOT / 'firstwell.db'
DATA = ROOT / 'data'
PAGES = ROOT / 'pages'  # HTML pages; still served at /<name>.html
UPLOADS = ROOT / 'uploads'
PENDING = ROOT / 'pending'
REPORTS = ('inventory','movement','my_price','my_perf','sg_price','sg_perf')
NAMES = dict(zip(REPORTS, ('Avixo Inventory','Avixo Movement','Shopee MY Prices',
                          'Shopee MY Sales','Shopee SG Prices','Shopee SG Sales')))
app = Flask(__name__, static_folder=None)
app.config['MAX_CONTENT_LENGTH'] = 35 * 1024 * 1024


# Supabase Auth protects the existing Flask pages and SQLite data.
# Only verified staff on ALLOWED_EMAILS can sign in. Fail closed otherwise.
from urllib import request as urlrequest, error as urlerror
from html import escape as html_escape
from functools import wraps


def load_local_config():
    # No dependency on python-dotenv; never commit .env to git.
    path = ROOT / '.env'
    if path.exists():
        for line in path.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            key, value = line.split('=', 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_local_config()
SUPABASE_URL = os.getenv('SUPABASE_URL', '').rstrip('/')
SUPABASE_PUBLISHABLE_KEY = os.getenv('SUPABASE_PUBLISHABLE_KEY', '')
ALLOWED_EMAILS = {x.strip().casefold() for x in os.getenv('ALLOWED_EMAILS', '').split(',') if x.strip()}
AUTH_SECONDS = 8 * 60 * 60
COOKIE_NAME = 'firstwell_session'


def auth_request(path, method='GET', payload=None, token=None):
    if not SUPABASE_URL.startswith('https://') or not SUPABASE_PUBLISHABLE_KEY:
        raise RuntimeError('Supabase Auth is not configured. Check .env')
    headers = {'apikey': SUPABASE_PUBLISHABLE_KEY, 'Content-Type':'application/json'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    body = json.dumps(payload).encode('utf-8') if payload is not None else None
    req = urlrequest.Request(SUPABASE_URL + path, data=body, headers=headers, method=method)
    with urlrequest.urlopen(req, timeout=12) as res:
        return json.loads(res.read())


def _session_client():
    """Server-only Supabase client. Never expose service-role credentials."""
    from supabase import create_client
    url = os.getenv('SUPABASE_URL', '').strip()
    key = os.getenv('SUPABASE_SERVICE_ROLE_KEY', '').strip()
    if not url.startswith('https://') or not key:
        raise RuntimeError('Supabase server credentials are not configured')
    return create_client(url, key)


def _session_hash(raw):
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def current_session():
    raw = request.cookies.get(COOKIE_NAME, '')
    if not raw:
        return None
    now = int(dt.datetime.now(dt.timezone.utc).timestamp())
    rows = (_session_client().table('fs_app_auth_sessions')
            .select('email,user_id,csrf_token,expires_at')
            .eq('token_hash', _session_hash(raw))
            .gt('expires_at', now)
            .limit(1).execute().data or [])
    session = rows[0] if rows else None
    if session and session['email'].casefold() not in ALLOWED_EMAILS:
        return None
    return session


@app.before_request
def require_staff_login():
    if request.path in ('/login', '/healthz'):
        return None
    # Legacy SQLite routes are unsafe on serverless hosting until migrated.
    legacy_prefixes = ('/api/status', '/api/available', '/api/preview',
                       '/api/accept', '/api/process')
    if os.getenv('VERCEL') and request.path in legacy_prefixes:
        return jsonify(error='Legacy report endpoint not yet migrated to Supabase'), 503
    session = current_session()
    if not session:
        if request.path.startswith('/api/'):
            return jsonify(error='Please sign in again.'), 401
        return redirect('/login')
    g.staff = session
    if request.method in ('POST', 'PUT', 'PATCH', 'DELETE'):
        if request.headers.get('X-CSRF-Token', '') != session['csrf_token']:
            return jsonify(error='Invalid security token. Refresh the page and try again.'), 403


@app.get('/healthz')
def healthz():
    return jsonify(status='running')


LOGIN_HTML = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>FirstWell Essentials · Staff Sign in</title><style>body{font:16px system-ui;background:#f4f5f2;color:#17201d;display:grid;place-items:center;min-height:100vh;margin:0}.panel{background:#fff;border:1px solid #dde1dc;border-radius:16px;padding:32px;width:min(420px,90vw);box-sizing:border-box}label{display:block;margin:18px 0 6px;font-weight:600}input,button{width:100%;padding:12px;font:inherit;box-sizing:border-box;border-radius:8px}input{border:1px solid #cfd7d1}button{border:0;background:#0e5a52;color:white;font-weight:700;cursor:pointer;margin-top:22px}.error{color:#a3262e}small{color:#63716a}</style></head><body><main class="panel"><h1>FirstWell Essentials Staff Login</h1><p>Inventory & Business Analytics</p>{error}<form method="post" action="/login"><label for="email">Staff email</label><input id="email" name="email" type="email" autocomplete="username" required><label for="password">Password</label><input id="password" name="password" type="password" autocomplete="current-password" required><button type="submit">Sign in</button></form><p><small>Only approved staff accounts can access reports.</small></p></main></body></html>"""


@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'GET':
        return LOGIN_HTML.replace('{error}', '')
    email = request.form.get('email','').strip().casefold()
    password = request.form.get('password','')
    error_msg = 'Login failed. Check your credentials and staff access.'
    if not ALLOWED_EMAILS:
        app.logger.warning('Login refused: ALLOWED_EMAILS is empty. Is .env beside app.py, or is the variable set on Vercel?')
    elif email not in ALLOWED_EMAILS:
        app.logger.warning('Login refused: that email is not in ALLOWED_EMAILS.')
    if not ALLOWED_EMAILS or email not in ALLOWED_EMAILS or len(password) > 1000:
        return LOGIN_HTML.replace('{error}', '<p class="error">'+error_msg+'</p>'), 403
    try:
        result = auth_request('/auth/v1/token?grant_type=password','POST',{'email':email,'password':password})
        access_token = result.get('access_token')
        user = auth_request('/auth/v1/user', token=access_token)
        actual_email = (user.get('email') or '').casefold()
        if not user.get('id') or actual_email != email or not user.get('email_confirmed_at'):
            raise ValueError('Email is not verified')
    except (urlerror.URLError, TimeoutError, ValueError, KeyError, RuntimeError) as exc:
        # Reason only (never the password or keys) so the server log shows why sign-in failed.
        app.logger.warning('Login refused by Supabase Auth: %s', getattr(exc, 'code', None) or type(exc).__name__ + ': ' + str(exc)[:120])
        return LOGIN_HTML.replace('{error}', '<p class="error">'+error_msg+'</p>'), 403
    raw = secrets.token_urlsafe(32)
    now = int(dt.datetime.now(dt.timezone.utc).timestamp())
    try:
        (_session_client().table('fs_app_auth_sessions').insert({
            'token_hash': _session_hash(raw),
            'email': actual_email,
            'user_id': user['id'],
            'csrf_token': secrets.token_urlsafe(32),
            'expires_at': now + AUTH_SECONDS,
        }).execute())
    except Exception:
        app.logger.exception('Could not create staff session')
        return LOGIN_HTML.replace('{error}', '<p class="error">Login temporarily unavailable.</p>'), 503
    response = make_response(redirect('/overview.html'))
    response.set_cookie(COOKIE_NAME, raw, max_age=AUTH_SECONDS, httponly=True, samesite='Lax',
                        secure=bool(os.getenv("VERCEL")) or request.is_secure, path='/')
    response.headers['Cache-Control'] = 'no-store'
    return response


@app.get('/api/auth/session')
def auth_session():
    return jsonify(email=g.staff['email'],csrf_token=g.staff['csrf_token'])


@app.post('/api/auth/logout')
def logout():
    cookie = request.cookies.get(COOKIE_NAME, '')
    if cookie:
        _session_client().table('fs_app_auth_sessions').delete().eq(
            'token_hash', _session_hash(cookie)).execute()
    response = jsonify(ok=True)
    response.delete_cookie(COOKIE_NAME, path='/')
    return response



def connection():
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys = ON')
    return db


def init_db():
    if os.getenv('VERCEL'):
        raise RuntimeError('SQLite initialization is disabled on Vercel; migrate legacy report routes first')
    for folder in (DATA, UPLOADS, PENDING, ROOT/'backups'):
        folder.mkdir(exist_ok=True)
    with connection() as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS accepted_files (
            id INTEGER PRIMARY KEY, month TEXT NOT NULL, kind TEXT NOT NULL,
            original_name TEXT NOT NULL, disk_path TEXT NOT NULL,
            file_sha256 TEXT NOT NULL, content_sha256 TEXT NOT NULL,
            coverage_end TEXT, snapshot_date TEXT, accepted_at TEXT DEFAULT CURRENT_TIMESTAMP,
            active INTEGER NOT NULL DEFAULT 1,
            UNIQUE(month,kind,id));
        CREATE INDEX IF NOT EXISTS accepted_active ON accepted_files(month,kind,active);
        CREATE TABLE IF NOT EXISTS source_records (
            month TEXT NOT NULL, kind TEXT NOT NULL, record_key TEXT NOT NULL,
            content_hash TEXT NOT NULL, payload TEXT NOT NULL,
            PRIMARY KEY(month,kind,record_key));
        CREATE TABLE IF NOT EXISTS pending_previews (
            token TEXT PRIMARY KEY, month TEXT, kind TEXT, path TEXT,
            original_name TEXT, file_hash TEXT, content_hash TEXT,
            records_json TEXT, changes_json TEXT, coverage_end TEXT,
            snapshot_date TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS months (
            month TEXT PRIMARY KEY, status TEXT NOT NULL DEFAULT 'Draft',
            fx REAL, stock_date TEXT, processed_at TEXT);
        CREATE TABLE IF NOT EXISTS audit (
            id INTEGER PRIMARY KEY, month TEXT, kind TEXT, action TEXT,
            details TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        ''')


def respond_error(message, code=400):
    return jsonify(error=str(message)), code


def clean(value):
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()
    if isinstance(value, float):
        return round(value, 6)
    if isinstance(value, dict):
        return {str(k): clean(v) for k,v in sorted(value.items())}
    if isinstance(value, (list,tuple)):
        return [clean(v) for v in value]
    return value


def digest(value):
    return hashlib.sha256(json.dumps(clean(value), ensure_ascii=False,
           sort_keys=True, separators=(',',':')).encode()).hexdigest()


def normalized_rows(path, kind):
    """Records keyed by source-native identities. Parent and variation rows are distinct."""
    records = {}
    def put(key, payload):
        if key in records:
            if digest(records[key]) != digest(payload):
                raise ValueError(f'Conflicting repeated record identifier: {key}. Resolve in the source file.')
            return
        records[key] = clean(payload)
    if kind == 'inventory':
        products, batches, source_date = read_inventory(path)
        for p in products:
            key = str(p['id']) if p['id'] is not None else 'name:'+p['name']
            put(key, dict(product=p, batches=sorted(batches.get(p['name'],[]),key=digest)))
    elif kind == 'movement':
        movement, period = read_movement(path)
        for name, details in movement.items():
            put(name, details)
    elif kind in ('my_price','sg_price'):
        by_var, _ = read_shopee_price(path)
        for (item,variation), price in by_var.items():
            put(item+'|'+variation, dict(price=price))
    else:
        units = 'Units (Confirmed Order)' if kind == 'my_perf' else 'Units (Paid Order)'
        sales = 'Sales (Confirmed Order) (MYR)' if kind == 'my_perf' else 'Sales (Paid Order) (SGD)'
        parents, variations = read_shopee_perf(path, units, sales)
        for item, perf in parents.items():
            put(item+'|PARENT', perf)
        for (item,var), perf in variations.items():
            put(item+'|VAR|'+var, perf)
    if not records:
        raise ValueError('No usable records found. Check report structure.')
    return records


def detect(path, filename):
    """Reject ambiguous MY/SG performance and price reports rather than guessing."""
    wb = open_workbook(path)
    sheets = set(wb.sheetnames)
    if {'Summary','Multiple Expiry'} <= sheets:
        return 'inventory'
    if 'Top Performing Products' in sheets:
        h = [str(c.value or '') for c in wb['Top Performing Products'][1]]
        if 'Units (Confirmed Order)' in h and 'Sales (Confirmed Order) (MYR)' in h:
            return 'my_perf'
        if 'Units (Paid Order)' in h and 'Sales (Paid Order) (SGD)' in h:
            return 'sg_perf'
    ws = wb.worksheets[0]
    first = [[str(c.value or '').strip() for c in row] for row in ws.iter_rows(min_row=1,max_row=12)]
    if any(row and row[0] == 'Category' and 'Closing Balance' in row and 'Sold' in row for row in first):
        return 'movement'
    if any({'Product ID','Variation ID','Price'} <= set(row) for row in first):
        low = filename.lower()
        if re.search(r'(^|[^a-z])sg([^a-z]|$)|singapore', low):
            return 'sg_price'
        if re.search(r'(^|[^a-z])my([^a-z]|$)|malaysia', low):
            return 'my_price'
        raise ValueError('Shopee price file detected, but MY/SG cannot be determined. Add _my or _sg to the filename.')
    raise ValueError('Unrecognized spreadsheet layout. Upload one of the six original report formats.')


def parse_coverage(filename, kind, month, coverage_end, snapshot_date, path):
    if kind.endswith('_perf'):
        match = re.search(r'(20\d{6})[_-](20\d{6})', filename)
        if not match:
            raise ValueError('Shopee performance filename must include start and end dates (YYYYMMDD_YYYYMMDD).')
        start, end = (dt.datetime.strptime(x,'%Y%m%d').date() for x in match.groups())
        if end < start or start.strftime('%Y-%m') != month or end.strftime('%Y-%m') != month:
            raise ValueError('Sales report dates do not match the selected reporting month.')
        if start.day != 1:
            raise ValueError('This first version accepts only cumulative reports starting on day 1. Do not upload overlapping partial ranges.')
        if coverage_end and coverage_end != end.isoformat():
            raise ValueError('Coverage date does not match Shopee filename.')
        coverage_end = end.isoformat()
    if kind == 'inventory':
        _, _, embedded_date = read_inventory(path)
        try:
            actual_inventory_date = dt.datetime.strptime(str(embedded_date).split(' ')[0], '%d/%m/%Y').date()
            if snapshot_date and snapshot_date != actual_inventory_date.isoformat():
                raise ValueError(f'Inventory snapshot date disagrees with Excel date ({actual_inventory_date}).')
        except (ValueError, TypeError) as exc:
            if 'disagrees' in str(exc): raise
        if not snapshot_date:
            try:
                snapshot_date = actual_inventory_date.isoformat()
            except (NameError, ValueError, TypeError):
                raise ValueError('Cannot detect the inventory snapshot date. Open Advanced options and enter it.')
        snap = dt.date.fromisoformat(snapshot_date)
        if snap.strftime('%Y-%m') != month and snap != (dt.date(int(month[:4])+(month[5:]=='12'),int(month[5:])%12+1,1)):
            raise ValueError('Inventory date must be in the selected month or the first day of the next month.')
    if kind == 'movement':
        _, embedded_period = read_movement(path)
        period_match = re.search(r'From:\s*(\d{2}/\d{2}/\d{4})\s*-\s*To:\s*(\d{2}/\d{2}/\d{4})',str(embedded_period))
        if period_match:
            start_actual, end_actual = [dt.datetime.strptime(x,'%d/%m/%Y').date() for x in period_match.groups()]
            if start_actual.strftime('%Y-%m') != month or start_actual.day != 1 or end_actual.strftime('%Y-%m') != month:
                raise ValueError('Movement report must be month-to-date for the selected month.')
            if coverage_end and coverage_end != end_actual.isoformat():
                raise ValueError(f'Movement period end disagrees with file ({end_actual}).')
            coverage_end = end_actual.isoformat()
        if not coverage_end:
            raise ValueError('Movement requires the period end date (month-to-date or month-end).')
        if not coverage_end.startswith(month):
            raise ValueError('Movement period end date must be within the selected month.')
    if coverage_end and not coverage_end.startswith(month):
        raise ValueError('Coverage end date does not match the month.')
    return coverage_end or '', snapshot_date or ''


def csv_to_xlsx(path, kind):
    """Limited CSV conversion: native movement / performance / price column layouts only."""
    from openpyxl import Workbook
    if kind == 'inventory':
        raise ValueError('Avixo Inventory requires XLSX with Summary and Multiple Expiry sheets.')
    data = None
    for enc in ('utf-8-sig','cp1252'):
        try:
            with open(path, encoding=enc, newline='') as f:
                data = list(csv.reader(f))
            break
        except UnicodeDecodeError:
            continue
    if not data:
        raise ValueError('CSV is empty or cannot be decoded.')
    wb = Workbook()
    ws = wb.active
    if kind.endswith('_perf'):
        ws.title = 'Top Performing Products'
    elif kind.endswith('_price'):
        # Original Shopee price reader expects headers on row 3 and data on row 7.
        ws.append([]);ws.append([])
        for i,row in enumerate(data):
            ws.append(row)
            if i == 0:
                ws.append([]);ws.append([]);ws.append([])
    if not kind.endswith('_price'):
        for row in data:
            ws.append(row)
    dest = PENDING / (secrets.token_hex(12)+'.xlsx')
    wb.save(dest)
    return dest


@app.get('/api/inv/config')
def inventory_config():
    """Public Supabase settings for the Inventory Update page (URL + publishable key only; never a secret)."""
    if not SUPABASE_URL.startswith('https://') or not SUPABASE_PUBLISHABLE_KEY:
        return jsonify(error='Supabase is not configured'), 503
    return jsonify(url=SUPABASE_URL, key=SUPABASE_PUBLISHABLE_KEY)


@app.get('/')
def root():
    return send_from_directory(PAGES,'overview.html')


@app.get('/weekly-sales.html')
def weekly_sales_moved():
    """Weekly sales now lives in the Upload Data page (Weekly sales tab)."""
    return redirect('/upload.html#weekly')


@app.get('/<path:filename>')
def static_file(filename):
    """Serve only the dashboard's approved pages and static assets."""
    allowed_pages = {
        'overview.html', 'index.html', 'analytics.html', 'product.html',
        'upload.html', 'bi.html', 'scrap.html', 'inventory.html', 'stock-after-sales.html',
    }
    if filename == 'auth-ui.js':  # old address, kept for pages cached in browsers
        return send_from_directory(ROOT / 'assets' / 'js', 'auth-ui.js')
    if filename in allowed_pages:
        return send_from_directory(PAGES, filename)
    allowed_data = (
        filename.startswith('data/')
        and filename.endswith(('.js', '.json'))
    )
    allowed_assets = (
        filename.startswith('assets/')
        and filename.endswith(('.css', '.js', '.png', '.jpg', '.jpeg', '.webp', '.svg'))
    )
    if '..' in filename or not (filename in allowed_pages or allowed_data or allowed_assets):
        return respond_error('Not found', 404)
    return send_from_directory(ROOT, filename)


@app.get('/api/status')
def status():
    with connection() as db:
        months = [dict(x) for x in db.execute('SELECT * FROM months ORDER BY month DESC')]
        files = [dict(x) for x in db.execute('SELECT month,kind,original_name,coverage_end,snapshot_date,accepted_at FROM accepted_files WHERE active=1 ORDER BY month DESC,kind')]
    for key in json.loads((DATA/'months.json').read_text()) if (DATA/'months.json').exists() else []:
        if not any(x['month'] == key['key'] for x in months):
            months.append({'month':key['key'],'status':'Historical','processed_at':None})
    months.sort(key=lambda x:x['month'],reverse=True)
    return jsonify(months=months,files=files, report_names=NAMES)


@app.get('/api/available')
def available():
    """Compute trustworthy source-level metrics from every accepted report independently.

    These are intentionally *not* combined across sources: Shopee performance can
    include listings not linked to Avixo, and inventory snapshots are not sales.
    """
    month=request.args.get('month','')
    if not re.fullmatch(r'20\d\d-(0[1-9]|1[0-2])',month):
        return respond_error('Invalid reporting month.')
    with connection() as db:
        sources={}
        for row in db.execute('SELECT kind,record_key,payload FROM source_records WHERE month=?',(month,)):
            sources.setdefault(row['kind'],{})[row['record_key']]=json.loads(row['payload'])
        published=db.execute('SELECT status,processed_at FROM months WHERE month=?',(month,)).fetchone()
    results={}
    if 'inventory' in sources:
        data=sources['inventory'].values()
        stock_units=0;stock_value=0;missing_cost=0
        for r in data:
            p=r['product']; batches=r.get('batches',[])
            stock_units+=sum(float(b.get('qty') or 0) for b in batches)
            stock_value+=sum(float(b.get('value_cost') or 0) for b in batches)
            missing_cost+=not bool(p.get('latest_cost'))
        results['inventory']={'products':len(sources['inventory']),'stock_units':round(stock_units,2),
                              'stock_value_rm':round(stock_value,2),'missing_cost_products':missing_cost,
                              'note':'Stock snapshot. Does not represent monthly sales.'}
    if 'movement' in sources:
        values=list(sources['movement'].values())
        results['movement']={'products':len(values),'clinic_units_sold':round(sum(float(x.get('sold') or 0) for x in values),2),
                             'note':'Units from Avixo movement report. Clinic revenue requires validated prices and product matching.'}
    for market in ('my','sg'):
        pk=market+'_perf';pr=market+'_price'
        if pk in sources:
            parents=[v for k,v in sources[pk].items() if k.endswith('|PARENT')]
            results[pk]={'parent_listings':len(parents),'units_sold':round(sum(float(v.get('units') or 0) for v in parents),2),
                         'sales_original_currency':round(sum(float(v.get('sales') or 0) for v in parents),2),
                         'currency':'MYR' if market=='my' else 'SGD',
                         'note':'Source-wide Shopee totals; may include products not linked to Avixo. No parent/variation double count.'}
        if pr in sources:
            results[pr]={'price_rows':len(sources[pr]),'note':'Current listing price snapshot; not sales.'}
    found=list(sources)
    return jsonify(month=month,available=results,received=found,
                   missing=[k for k in REPORTS if k not in sources],
                   ready_for_full=len(found)==len(REPORTS),
                   published_status=published['status'] if published else None,
                   note='Partial metrics are per source and provisional. Full matched inventory/financial dashboard requires all six reports.')


@app.post('/api/preview')
def preview():
    month = request.form.get('month','')
    if not re.fullmatch(r'20\d\d-(0[1-9]|1[0-2])',month):
        return respond_error('Select a valid reporting month (YYYY-MM).')
    file = request.files.get('file')
    if not file or not file.filename:
        return respond_error('Choose an Excel or CSV file.')
    suffix = Path(file.filename).suffix.lower()
    if suffix not in ('.xlsx','.csv'):
        return respond_error('Supported: XLSX or CSV. Convert legacy XLS to XLSX first.')
    original = secure_filename(file.filename)[:180]
    temporary = PENDING / (secrets.token_hex(12)+suffix)
    file.save(temporary)
    converted = None
    try:
        kind = request.form.get('kind','auto')
        if suffix == '.csv':
            if kind not in REPORTS:
                raise ValueError('For CSV, select the report type manually because worksheets are unavailable.')
            converted = csv_to_xlsx(temporary,kind)
            read_path = converted
        else:
            read_path = temporary
            detected = detect(read_path,original)
            if kind not in ('auto',detected):
                raise ValueError(f'File content indicates {NAMES[detected]}, but you selected {NAMES[kind]}.')
            kind = detected
        coverage_end, snapshot_date = parse_coverage(
            original,kind,month,request.form.get('coverage_end',''),request.form.get('snapshot_date',''),read_path)
        records = normalized_rows(read_path,kind)
        with connection() as db:
            existing = {x['record_key']:x['content_hash'] for x in db.execute(
                'SELECT record_key,content_hash FROM source_records WHERE month=? AND kind=?',(month,kind))}
            prev = db.execute('SELECT coverage_end,snapshot_date FROM accepted_files WHERE month=? AND kind=? AND active=1',(month,kind)).fetchone()
            if prev:
                previous_date = prev['snapshot_date'] if kind == 'inventory' else prev['coverage_end']
                current_date = snapshot_date if kind == 'inventory' else coverage_end
                if previous_date and current_date and current_date < previous_date:
                    raise ValueError(f'Older report ({current_date}) cannot overwrite newer accepted report ({previous_date}).')
            new_keys = set(records)-set(existing)
            shared = set(records)&set(existing)
            changed = [k for k in shared if digest(records[k]) != existing[k]]
            identical = [k for k in shared if k not in changed]
            missing = sorted(set(existing)-set(records))
            changes = dict(new=len(new_keys),changed=len(changed),identical=len(identical),missing=len(missing),
                           examples=[{'key':k,'new':records[k]} for k in changed[:8]],
                           missing_examples=missing[:12])
            token = secrets.token_urlsafe(24)
            file_hash = hashlib.sha256(temporary.read_bytes()).hexdigest()
            content_hash = digest(records)
            db.execute('''INSERT INTO pending_previews(token,month,kind,path,original_name,file_hash,content_hash,
                          records_json,changes_json,coverage_end,snapshot_date) VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
                       (token,month,kind,str(read_path),original,file_hash,content_hash,json.dumps(records),
                        json.dumps(changes),coverage_end,snapshot_date))
        if converted:
            temporary.unlink(missing_ok=True)
        return jsonify(token=token,month=month,kind=kind,report=NAMES[kind],changes=changes,
                       coverage_end=coverage_end,snapshot_date=snapshot_date,records=len(records))
    except Exception as e:
        temporary.unlink(missing_ok=True)
        if converted: converted.unlink(missing_ok=True)
        return respond_error(str(e))


@app.post('/api/accept')
def accept():
    body = request.get_json(silent=True) or {}
    token = body.get('token')
    if not token: return respond_error('Missing upload preview token.')
    with connection() as db:
        db.execute('BEGIN IMMEDIATE')
        pending = db.execute('SELECT * FROM pending_previews WHERE token=?',(token,)).fetchone()
        if not pending: return respond_error('Preview expired or already accepted. Upload again.',409)
        month,kind = pending['month'],pending['kind']
        # Re-compare immediately before commit to avoid stale previews.
        records = json.loads(pending['records_json'])
        existing = {x['record_key']:x['content_hash'] for x in db.execute(
            'SELECT record_key,content_hash FROM source_records WHERE month=? AND kind=?',(month,kind))}
        current=db.execute('SELECT coverage_end,snapshot_date FROM accepted_files WHERE month=? AND kind=? AND active=1',(month,kind)).fetchone()
        if current:
            old_date=current['snapshot_date'] if kind=='inventory' else current['coverage_end']
            incoming=pending['snapshot_date'] if kind=='inventory' else pending['coverage_end']
            if old_date and incoming and incoming<old_date:
                return respond_error('A newer report has been saved since preview. Upload the updated file again.',409)
        changes = json.loads(pending['changes_json'])
        actual_changed = sum(digest(v)!=existing.get(k) for k,v in records.items() if k in existing)
        actual_new = sum(k not in existing for k in records)
        if actual_new!=changes['new'] or actual_changed!=changes['changed'] or len(set(existing)-set(records))!=changes['missing']:
            return respond_error('Saved data changed since preview. Upload again to recheck.',409)
        if changes['missing'] and not body.get('confirm_missing'):
            return respond_error('Some earlier records are missing. Confirm that the new file is a complete replacement.',409)
        if changes['new']==0 and changes['changed']==0 and changes['missing']==0:
            db.execute('DELETE FROM pending_previews WHERE token=?',(token,))
            duplicate_path=Path(pending['path'])
            # No changes to published results or month status.
            duplicate_response=jsonify(ok=True,month=month,kind=kind,changes=changes,status='Identical',identical=True)
            # Drop file after the DB context finishes below.
            duplicate_path.unlink(missing_ok=True)
            return duplicate_response
        src = Path(pending['path'])
        if not src.is_file(): return respond_error('Pending file not found. Upload again.',409)
        # Atomically write accepted file, then commit database transaction.
        dest_dir=UPLOADS/month/kind
        dest_dir.mkdir(parents=True,exist_ok=True)
        dest=dest_dir/(secrets.token_hex(10)+'.xlsx')
        shutil.copy2(src,dest)
        db.execute('UPDATE accepted_files SET active=0 WHERE month=? AND kind=?',(month,kind))
        db.execute('INSERT INTO accepted_files(month,kind,original_name,disk_path,file_sha256,content_sha256,coverage_end,snapshot_date) VALUES(?,?,?,?,?,?,?,?)',
                   (month,kind,pending['original_name'],str(dest),pending['file_hash'],pending['content_hash'],pending['coverage_end'],pending['snapshot_date']))
        # Full source report replacement: aggregates never accumulate.
        db.execute('DELETE FROM source_records WHERE month=? AND kind=?',(month,kind))
        db.executemany('INSERT INTO source_records(month,kind,record_key,content_hash,payload) VALUES(?,?,?,?,?)',
                       [(month,kind,k,digest(v),json.dumps(v)) for k,v in records.items()])
        db.execute("INSERT INTO months(month,status) VALUES(?, 'Draft') ON CONFLICT(month) DO UPDATE SET status='Draft'",(month,))
        db.execute('INSERT INTO audit(month,kind,action,details) VALUES(?,?,?,?)',
                   (month,kind,'ACCEPT',json.dumps(changes)))
        db.execute('DELETE FROM pending_previews WHERE token=?',(token,))
    src.unlink(missing_ok=True)
    return jsonify(ok=True,month=month,kind=kind,changes=changes,status='Draft')


def final_month_date(month):
    y,m=map(int,month.split('-'))
    return (dt.date(y+(m==12),m%12+1,1)-dt.timedelta(days=1)).isoformat()


@app.post('/api/process')
def process():
    body=request.get_json(silent=True) or {}
    month=body.get('month','')
    if not re.fullmatch(r'20\d\d-(0[1-9]|1[0-2])',month):return respond_error('Invalid month.')
    try:
        fx=float(body.get('fx'))
        if not 0 < fx < 10: raise ValueError()
    except (ValueError,TypeError):
        return respond_error('Enter a valid SGD → MYR conversion rate for the reporting month.')
    with connection() as db:
        rows=db.execute('SELECT kind,disk_path,coverage_end,snapshot_date FROM accepted_files WHERE month=? AND active=1',(month,)).fetchall()
    found={row['kind']:row for row in rows}
    missing=[NAMES[k] for k in REPORTS if k not in found]
    if missing: return respond_error('Missing required reports: '+', '.join(missing))
    end=final_month_date(month)
    if body.get('final',False):
        for kind in ('movement','my_perf','sg_perf'):
            if found[kind]['coverage_end'] != end:
                return respond_error(f'Cannot Finalize: {NAMES[kind]} only covers through {found[kind]["coverage_end"]}; expected {end}.')
        snapshot=found['inventory']['snapshot_date']
        next_day=(dt.date.fromisoformat(end)+dt.timedelta(days=1)).isoformat()
        if snapshot not in (end,next_day):
            return respond_error('Final inventory snapshot must be month-end or the next day before new movements.')
    snapshot=found['inventory']['snapshot_date']
    out=DATA/(month+'.json')
    # Processor writes JSON/JS and months index only on success. Restore outputs if validation fails.
    backup={p:p.read_bytes() for p in [out,DATA/(month+'.js'),DATA/'months.js',DATA/'months.json'] if p.exists()}
    cmd=[sys.executable,str(ROOT/'process_month.py'),'--month',month,'--fx',str(fx),'--stock-date',snapshot,'--out',str(out)]
    for k in REPORTS:
        cmd += ['--'+k.replace('_','-'),found[k]['disk_path']]
    run=subprocess.run(cmd,capture_output=True,text=True,timeout=120,cwd=ROOT)
    if run.returncode:
        for p in [out,DATA/(month+'.js'),DATA/'months.js',DATA/'months.json']:
            if p in backup:p.write_bytes(backup[p])
            else:p.unlink(missing_ok=True)
        return respond_error('Processing failed: '+(run.stderr or run.stdout)[-1800:])
    with connection() as db:
        db.execute('INSERT INTO months(month,status,fx,stock_date,processed_at) VALUES(?,?,?,?,CURRENT_TIMESTAMP) '
                   'ON CONFLICT(month) DO UPDATE SET status=excluded.status,fx=excluded.fx,stock_date=excluded.stock_date,processed_at=CURRENT_TIMESTAMP',
                   (month,'Final' if body.get('final',False) else 'Draft',fx,snapshot))
        db.execute('INSERT INTO audit(month,kind,action,details) VALUES(?,?,?,?)',
                   (month,'all','FINALIZE' if body.get('final',False) else 'PROCESS',run.stdout[-3000:]))
    return jsonify(ok=True,month=month,status='Final' if body.get('final',False) else 'Draft',log=run.stdout)


@app.errorhandler(413)
def too_big(error):
    return respond_error('File is larger than the 35 MB upload limit.',413)


# ============================================================
# Supabase read-only API (staff-only via require_staff_login)
# Keep service-role credentials on the Flask server, never JS.
# ============================================================

def _supabase_read_client():
    """Create a server-side Supabase client using existing .env settings."""
    from supabase import create_client

    url = os.getenv('SUPABASE_URL', '').strip()
    key = os.getenv('SUPABASE_SERVICE_ROLE_KEY', '').strip()
    if not url.startswith('https://') or not key:
        raise RuntimeError('Supabase database connection is not configured')
    return create_client(url, key)


def _supabase_fetch_all(db, table, columns, order_columns):
    """Read all rows with deterministic paging (Supabase may limit page size)."""
    rows = []
    page_size = 500
    offset = 0
    while True:
        query = db.table(table).select(columns)
        for col in order_columns:
            query = query.order(col)
        batch = query.range(offset, offset + page_size - 1).execute().data or []
        rows.extend(batch)
        if len(batch) < page_size:
            break
        offset += page_size
    return rows


@app.get('/api/products')
def supabase_products():
    """Return all Avixo product identities from Supabase."""
    try:
        db = _supabase_read_client()
        products = _supabase_fetch_all(
            db, 'products', 'id,avixo_id,name,category,stock_unit', ['avixo_id']
        )
        return jsonify(success=True, source='supabase',
                       count=len(products), products=products)
    except Exception:
        app.logger.exception('Unable to retrieve Supabase products')
        return jsonify(error='Unable to load products from Supabase'), 503


@app.get('/api/inventory')
def supabase_inventory():
    """Read the latest complete-date inventory snapshot and expiry batches.

    Missing snapshot quantities are null, not zero. This endpoint shows
    historical snapshots, not live stock. It never writes to Supabase.
    """
    try:
        db = _supabase_read_client()
        products = _supabase_fetch_all(
            db, 'products', 'id,avixo_id,name,category,stock_unit', ['avixo_id']
        )
        snapshots = _supabase_fetch_all(
            db, 'inventory_snapshots',
            'product_id,snapshot_date,quantity,latest_cost_rm,'
            'clinic_list_price_rm,stock_value_rm,summary_balance',
            ['snapshot_date', 'product_id']
        )
        batches = _supabase_fetch_all(
            db, 'inventory_batches',
            'product_id,snapshot_date,batch_number,expiry_date,quantity',
            ['snapshot_date', 'product_id', 'batch_number']
        )

        latest_date = max(
            (row['snapshot_date'] for row in snapshots if row.get('snapshot_date')),
            default=None
        )
        stock_by_product = {
            row['product_id']: row for row in snapshots
            if row['snapshot_date'] == latest_date
        }
        batches_by_product = {}
        for batch in batches:
            if batch['snapshot_date'] != latest_date:
                continue
            batches_by_product.setdefault(batch['product_id'], []).append({
                'batch_number': batch['batch_number'],
                'expiry_date': batch['expiry_date'],
                'quantity': batch['quantity'],
            })

        inventory = []
        total_units = 0.0
        total_value = 0.0
        for product in products:
            product_id = product['id']
            stock = stock_by_product.get(product_id)
            quantity = (float(stock['quantity']) if stock and
                        stock.get('quantity') is not None else None)
            stock_value = (float(stock['stock_value_rm']) if stock and
                           stock.get('stock_value_rm') is not None else None)
            if quantity is not None:
                total_units += quantity
            if stock_value is not None:
                total_value += stock_value

            inventory.append({
                'product_id': product_id,
                'avixo_id': product['avixo_id'],
                'name': product['name'],
                'category': product['category'],
                'stock_unit': product['stock_unit'],
                'snapshot_date': stock['snapshot_date'] if stock else None,
                'stock_quantity': quantity,
                'stock_value_rm': stock_value,
                'latest_cost_rm': stock['latest_cost_rm'] if stock else None,
                'clinic_list_price_rm': stock['clinic_list_price_rm'] if stock else None,
                'summary_balance': stock['summary_balance'] if stock else None,
                'batches': batches_by_product.get(product_id, []),
            })

        return jsonify(
            success=True,
            source='supabase',
            snapshot_date=latest_date,
            product_count=len(products),
            products_with_snapshot=len(stock_by_product),
            total_stock_units=round(total_units, 2),
            total_stock_value_rm=round(total_value, 2),
            inventory=inventory,
            note='Historical inventory snapshot, not live stock levels.'
        )
    except Exception:
        app.logger.exception('Unable to retrieve Supabase inventory')
        return jsonify(error='Unable to load inventory from Supabase'), 503

# Staff-protected Supabase XLSX preview/import API. Existing upload routes remain for legacy use.
from backend.supabase_upload import register_upload_api
register_upload_api(app)

# Read-only Business Intelligence endpoints, queried from Supabase views.
from backend.bi_api import register_bi_api
register_bi_api(app)

# Read-only bridge: expose Supabase reporting months to legacy Inventory/Analytics/Product pages.
from backend.monthly_data_api import register_monthly_data_api
register_monthly_data_api(app)

# Processed monthly dashboard data (same JSON as the original files) stored in Supabase.
from backend.dashboard_api import register_dashboard_api
register_dashboard_api(app)

# Price Watch: competitor Shopee prices (Apify) stored in the fs_competitor_* / fs_scrape_* tables.
from backend.scrap_api import register_scrap_api
register_scrap_api(app)

# Weekly sales uploads (Shopee MY/SG + clinic movement units). No inventory.
from backend.weekly_sales_api import register_weekly_sales_api
register_weekly_sales_api(app)

from backend.stock_after_sales_api import register_stock_after_sales_api
register_stock_after_sales_api(app)

# Shopee listing -> Avixo product links (review sheet upload) + re-match of uploaded sales.
from backend.links_api import register_links_api
register_links_api(app)


@app.after_request
def prevent_sensitive_caching(response):
    if request.path != '/healthz':
        response.headers['Cache-Control'] = 'private, no-store'
    return response
