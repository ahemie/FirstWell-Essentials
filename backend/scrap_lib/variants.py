"""Split a Shopee listing that has several variations (sizes, flavours, ...) into one product per variation.

Our catalog stores one row per Shopee item. When an item has named variations, staff want one product per
variation (for example "Cetaphil Moisturizing Cream 100g"), each with its own keyword and price.
"""
import re

_UNIT = r'(?:g|gm|kg|ml|l|oz|s|pcs|pc|caps|capsules|tabs|tablets|sachets|gummies)'
_QTY = rf"\d+(?:\.\d+)?\s*(?:{_UNIT}['’]?s?|['’]s)\b"
_SIZE_LIST = re.compile(rf"{_QTY}(?:\s*(?:/|&|\+)\s*{_QTY})+", re.I)
_EXP_BRACKET = re.compile(r"\s*[\[(][^\])]*\bEXP[^\])]*[\])]", re.I)
_EMOJI = re.compile('[\U0001F300-\U0001FAFF☀-➿]')


def _norm(text):
    return re.sub(r'[^a-z0-9+]', '', str(text).lower())


def _squash(text):
    text = re.sub(r'[\[(]\s*[\])]', ' ', str(text))
    return re.sub(r'\s+', ' ', text).strip(' |-/&,')


def _glued_units(text):
    # "Cleanser250ML" -> "Cleanser 250ML"
    return re.sub(rf"(?<=[A-Za-z])(?=\d+(?:\.\d+)?\s*{_UNIT}\b)", ' ', text, flags=re.I)


def _parts(title):
    """(leading EXP tag, first '|' segment, EXP segment) of a catalog title."""
    title = _EMOJI.sub('', str(title or ''))
    lead = ''
    m = re.match(r"\s*([\[(][^\])]*(?:EXP|CLEARANCE)[^\])]*[\])])\s*", title, re.I)
    if m:
        lead, title = m.group(1), title[m.end():]
    segs = [s.strip() for s in title.split('|')]
    head = segs[0] if segs else ''
    exp = next((s for s in segs[1:] if re.match(r'\s*exp', s, re.I)), '')
    if not exp:
        m2 = re.search(r"\bEXP[:.\s]*\d{1,2}\s*[/.-]\s*\d{2,4}", head, re.I)
        if m2:
            exp = m2.group(0)
            head = head.replace(exp, ' ')
    return lead, _squash(head), exp


def _candidates(variation):
    base = _EXP_BRACKET.sub('', variation).strip()
    no_paren = re.sub(r'\s*\([^)]*\)', '', base).strip()
    no_qty = re.sub(rf"\s*{_QTY}\s*$", '', no_paren, flags=re.I).strip()
    first = no_paren.split(' ')[0] if no_paren else ''
    return {c for c in (base, no_paren, no_qty, first) if len(c) >= 3}


def variation_title(title, variation, all_variations):
    """The title of one variation as its own product."""
    lead, head, exp = _parts(title)
    vexp = re.search(r"[\[(]\s*(EXP[^\])]*)[\])]", variation, re.I)
    if vexp:
        exp = vexp.group(1)
    var = _squash(_EXP_BRACKET.sub('', variation))
    var_n = _norm(var)
    # "Biome ComfyPro Drops 8ml / Biome ImmunoPro Drops 10ml": the variation is one of the "/" parts of the head.
    segs = [s.strip() for s in re.split(r'\s+/\s+', head)]
    size_only = bool(re.fullmatch(rf"\s*{_QTY}\s*", var, re.I))   # "100g" alone cannot pick a part of the title
    hits = [s for s in segs if len(segs) > 1 and not size_only and var_n and var_n in _norm(s)]
    if len(hits) == 1:
        name = hits[0]
    else:
        base = re.sub(r'\bseries\b\s*$', '', head, flags=re.I)
        base = _SIZE_LIST.sub(' ', base)
        cands = sorted({c for v in all_variations for c in _candidates(v)}, key=len, reverse=True)
        if cands:
            alt = '|'.join(re.escape(c) for c in cands)
            base = re.sub(rf"(?:{alt})(?:\s*/\s*(?:{alt}))+", ' ', base, flags=re.I)
        base = _squash(_EXP_BRACKET.sub('', base))
        base = _squash(re.sub(r'\(\s*\)', ' ', base))
        # A quantity that the variation states again, such as "(15's)" + "Mango 15's", is written once.
        base = re.sub(rf"\(\s*({_QTY})\s*\)", lambda m: ' ' if _norm(m.group(1)) in var_n else m.group(0), base, flags=re.I)
        base = _squash(base)
        # Drop words the variation repeats from the end of the base ("... with Xylitol" + "Xylitol 100ml").
        bw, vw = base.split(), var.split()
        for k in range(min(len(bw), len(vw)), 0, -1):
            if [w.lower() for w in bw[-k:]] == [w.lower() for w in vw[:k]]:
                bw = bw[:-k]
                break
        if bw and vw and re.fullmatch(_QTY, bw[-1], re.I) and _norm(bw[-1]) == _norm(vw[-1]):
            bw = bw[:-1]
        name = _squash(' '.join(bw + vw))
        if var_n and var_n in _norm(base):
            name = base
    name = _squash(_glued_units(name))
    out = (f'[{lead.strip("[]()")}] ' if lead else '') + name
    return out + (f' | {_squash(exp)}' if exp else '')


def expand_variations(rows):
    """One row per variation for items that have 2+ named variations; other rows are returned unchanged."""
    out = []
    for row in rows:
        vs = [v for v in (row.get('variations') or []) if str(v.get('name') or '').strip()]
        if len(vs) < 2:
            out.append({k: v for k, v in row.items() if k != 'variations'})
            continue
        names = [str(v['name']) for v in vs]
        for v in vs:
            item = {k: val for k, val in row.items() if k != 'variations'}
            item.update(title=variation_title(row.get('title', ''), str(v['name']), names)[:300],
                        variation=str(v['name']).strip(), variation_id=str(v.get('id') or ''), price=v.get('price'), stock=v.get('stock'))
            out.append(item)
    return out
