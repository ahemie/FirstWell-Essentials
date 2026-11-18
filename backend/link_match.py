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
    s = re.sub(r'(\d+)\s*(?:sachets?|tablets?|tabs?|capsules?|caps?|pcs|s)\b', r'\1s', s)   # 15 sachets / 30's -> 15s
    return s
def toks(name):
    return {t for t in re.findall(r'[a-z]+\+?|\d+(?:\.\d+)?'+UNIT+r'?', clean(name)) if t not in STOP}
def sizes(ts): return {t for t in ts if re.fullmatch(r'\d+(?:\.\d+)?(?:ml|g|gm|kg|l)', t)}   # pack sizes only (not mg / %)
def key_tokens(ts):
    # sizes/strengths, "+" codes (C+, M+) and 2-3 letter codes (HA, AR, TC); single letters are too noisy
    return {t for t in ts if re.fullmatch(r'\d+(?:\.\d+)?'+UNIT+'?', t) or t.endswith('+') or (2 <= len(t) <= 3 and t.isalpha())}
def covered(key, lt):
    if key in lt: return True
    m = re.fullmatch(r'(\d+(?:\.\d+)?)(?:ml|g|gm)', key)          # "100" in the listing counts for 100g / 100ml
    return bool(m) and m.group(1) in lt
def label_tokens(base, var):
    if not var:
        return toks(base)
    parts = base.split('|')
    v = toks(var)
    head = toks(parts[0])
    for part in parts[1:]:                       # the segment that names this variation (e.g. "Vitamin C ... Blackcurrant")
        if toks(part) & (v - sizes(v)): head |= toks(part)
    return ((head - sizes(head)) | v) if sizes(v) else (head | v)
def score(lt, label, pname):
    pt = toks(pname)
    if not pt: return 0
    return 0.75*len(lt & pt)/len(pt) + 0.25*difflib.SequenceMatcher(None, clean(label)[:80], clean(pname)).ratio()
def ok(lt, pname):
    pt = toks(pname)
    first = next(iter(re.findall(r'[a-z]+', clean(pname))), '')
    if first and first not in lt and first not in STOP: return False
    if not all(covered(k, lt) for k in key_tokens(pt)): return False
    ls, ps = sizes(lt), sizes(pt)
    return True
TYPES = {'cream', 'wash', 'lotion', 'ointment', 'gel', 'shampoo', 'spray', 'oil', 'balm', 'cleanser', 'soap', 'syrup',
         'drops', 'powder', 'patch', 'chewable', 'chewables', 'jelly', 'serum', 'mist', 'toner', 'physiotoner', 'scrub', 'bodywash', 'foam', 'sachets', 'tablets'}
def types(text):
    return {w for w in re.findall(r'[a-z]+', clean(text)) if w in TYPES}
def type_conflict(base, var, pname):
    # cream vs wash etc.: if both sides name a product type and they share none, it is a different product
    lt = types(var) or types(base.split('|')[0]) or types(base)
    pt = types(pname)
    return bool(lt and pt and not (lt & pt))
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
    good = [(s, p) for s, p in ranked[:8] if s >= 0.7 and ok(lt, p['name']) and not variant_conflict(lt, p['name'], products)
            and not type_conflict(base, var or '', p['name'])]
    if not good: return None, ranked
    if len(good) > 1 and good[0][0] - good[1][0] < 0.08: return None, ranked
    return good[0][1], ranked
