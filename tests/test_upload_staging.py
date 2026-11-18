"""Run: python3 tests/test_upload_staging.py  (no database access; fake Supabase client)."""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('SUPABASE_URL', 'http://x'); os.environ.setdefault('SUPABASE_SERVICE_ROLE_KEY', 'x')
from backend import supabase_upload as su

class Q:
    def __init__(s, t): s.t=t; s.op=None; s.f=[]; s.payload=None
    def delete(s): s.op='delete'; return s
    def insert(s, p): s.op='insert'; s.payload=p; return s
    def select(s, c): s.op='select'; return s
    def eq(s,k,v): s.f.append(('eq',k,v)); return s
    def lt(s,k,v): s.f.append(('lt',k,v)); return s
    def limit(s,n): return s
    def execute(s):
        rows=s.t.rows
        def ok(r): return all((r[k]==v) if o=='eq' else (r[k]<v) for o,k,v in s.f)
        if s.op=='insert': rows.append(dict(s.payload,created_at='2026-11-02T03:00:00+00:00')); return type('R',(),{'data':None})
        if s.op=='delete': s.t.rows=[r for r in rows if not ok(r)]; return type('R',(),{'data':None})
        return type('R',(),{'data':[r for r in rows if ok(r)]})
class T:
    rows=[]
class DB:
    def __init__(s): s.t=T()
    def table(s,name): assert name=='supabase_upload_previews'; return Q(s.t)

db=DB()
prepared={'tables':{'inventory_snapshots':[{'product_id':'p1','quantity':'5.00'}]},'kind':'inventory','month':'2026-10'}
su.stage_put(db,'tok','staff1','inventory','2026-10','2026-11-01','f.xlsx','fp',prepared)
got=su.stage_get(db,'tok','staff1'); assert got and got['prepared_json']==json.loads(json.dumps(prepared))
assert su.stage_get(db,'tok','other-staff') is None      # another user cannot read the preview
assert su.stage_get(db,'nope','staff1') is None
su.stage_delete(db,'tok'); assert su.stage_get(db,'tok','staff1') is None
print('PASS: upload staging in Supabase (put/get/owner check/delete)')
