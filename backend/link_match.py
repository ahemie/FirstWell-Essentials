"""Strict Shopee listing -> Avixo product name matcher. Links only when the match is clear; otherwise None.

Rules: brand (first word of the Avixo name) is in the listing; every size / short code / "+" token of the Avixo name
is in the listing; no variant code of the same brand (e.g. HA vs AR, C+ vs M+) contradicts; score >= 0.7 and a clear winner.
"""
import re, difflib
STOP = {'for','and','the','with','halal','of','exp','pcs','free','new','in','to','by','x','pack','set','series','care','kids','baby','skin','cream'}
UNIT = r'(?:ml|mls|g|gm|mg|s|l|kg|tabs?|caps?|sachets?|mcg|iu|%)'
def clean(name):
    s = str(name or '').lower().replace('’',"'")
    s = re.sub(r'\b([a-z])\.\s?([a-z])\b\.?', r'\1\2', s)
    s = re.sub(r'\[?\(?\s*exp[^|\]\)]*[\]\)]?', ' ', s)
    s = re.sub(r'(\d)\s*(ml|mls|g|gm|mg|kg|mcg|iu|%)\b', r'\1\2', s)
    s = s.replace('mls','ml').replace("'s",'s')
    return s
def toks(name):
    return {t for t in re.findall(r'[a-z]+\+?|\d+(?:\.\d+)?'+UNIT+r'?', clean(name)) if t not in STOP}
def sizes(ts): return {t for t in ts if re.fullmatch(r'\d+(?:\.\d+)?(?:ml|g|gm|kg|l)', t)}   # pack sizes only (not mg / %)
def key_tokens(ts):
    return {t for t in ts if re.fullmatch(r'\d+(?:\.\d+)?'+UNIT+'?', t) or t.endswith('+') or (len(t)<=3 and t.isalpha())}
def label_tokens(base, var):
    if not var:
        return toks(base)
    head = toks(base.split('|')[0])
    v = toks(var)
    return ((head - sizes(head)) | v) if sizes(v) else (head | v)
def score(lt, label, pname):
    pt = toks(pname)
    if not pt: return 0
    return 0.75*len(lt & pt)/len(pt) + 0.25*difflib.SequenceMatcher(None, clean(label)[:80], clean(pname)).ratio()
def ok(lt, pname):
    pt = toks(pname)
    first = next(iter(re.findall(r'[a-z]+', clean(pname))), '')
    if first and first not in lt and first not in STOP: return False
    if not key_tokens(pt) <= lt: return False
    ls, ps = sizes(lt), sizes(pt)
    return True
def brand(name):
    return next(iter(re.findall(r'[a-z]+', clean(name))), '')
def variant_conflict(lt, pname, products):
    b = brand(pname)
    vk = set()
    for p in products:
        if brand(p['name']) == b:
            vk |= {t for t in toks(p['name']) if (len(t) <= 3 and t.isalpha()) or t.endswith('+')}
    return bool((lt & vk) - toks(pname))
def pick(base, var, products):
    """Returns (product or None, ranked list of (score, product))."""
    lt = label_tokens(base, var); label = base + ' ' + (var or '')
    ranked = sorted(((score(lt, label, p['name']), p) for p in products), key=lambda z: -z[0])
    if re.search(r'bundle|\bset of\b|\bcoq\s?10|\bcombo\b', clean(label)):
        return None, ranked                      # multi-packs / different formulas are never auto-linked
    good = [(s, p) for s, p in ranked[:8] if s >= 0.7 and ok(lt, p['name']) and not variant_conflict(lt, p['name'], products)]
    if not good: return None, ranked
    if len(good) > 1 and good[0][0] - good[1][0] < 0.08: return None, ranked
    return good[0][1], ranked
