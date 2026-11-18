"""Pure helpers for the keyword scrape page: markets, URL parsing, relevance and price statistics."""
import html
import re
import statistics
from urllib.parse import unquote, urlsplit

from backend.scrap_lib.matching import dosage, name_tokens, pack

# Apify's actor takes lowercase country codes ('my', 'sg').
MARKETS = {
    'MY': {'country': 'my', 'currency': 'MYR', 'symbol': 'RM', 'label': 'Shopee Malaysia',
           'hosts': {'shopee.com.my', 'www.shopee.com.my'}},
    'SG': {'country': 'sg', 'currency': 'SGD', 'symbol': 'S$', 'label': 'Shopee Singapore',
           'hosts': {'shopee.sg', 'www.shopee.sg'}},
}


def clean_keyword(text):
    """Collapse whitespace; returns '' when the keyword is unusable (too short)."""
    value = re.sub(r'\s+', ' ', str(text or '')).strip()[:120]
    return value if len(value) >= 2 else ''


def parse_listing_url(url, market):
    """Shop and item IDs from a genuine https Shopee URL for the chosen market, else (None, None)."""
    if not isinstance(url, str) or market not in MARKETS:
        return None, None
    try:
        u = urlsplit(html.unescape(url.strip()))
        if u.scheme != 'https' or u.hostname not in MARKETS[market]['hosts'] or u.username or u.password or u.port is not None:
            return None, None
        path = unquote(u.path)
        m = re.search(r'-i\.(\d+)\.(\d+)/?$', path, re.I) or re.fullmatch(r'/product/(\d+)/(\d+)/?', path, re.I)
        return (m.group(1), m.group(2)) if m else (None, None)
    except (ValueError, TypeError):
        return None, None


def is_relevant(title, keyword):
    """Loose check that a result is the same kind of product as the keyword.

    Every distinctive keyword word must appear in the title. When the keyword states a pack or size
    (for example '5g x 6' or '400g') the title must state the same one. One-word keywords are allowed.
    """
    required = name_tokens(keyword)
    if not required:
        return True
    if not set(required).issubset(set(name_tokens(title))):
        return False
    wanted_pack = pack(keyword)
    if wanted_pack:
        return pack(title) == wanted_pack
    wanted_dose = dosage(keyword)
    if wanted_dose:
        return dosage(title) == wanted_dose
    return True


def summarize(rows):
    """Lowest / average / median / highest over the rows that count (included, not ours, priced)."""
    prices = [float(r['price']) for r in rows if r.get('included') and not r.get('is_own') and r.get('price') is not None
              and float(r['price']) > 0]
    if not prices:
        return {'included_count': 0, 'lowest': None, 'average': None, 'median': None, 'highest': None}
    return {'included_count': len(prices), 'lowest': round(min(prices), 2), 'average': round(sum(prices) / len(prices), 2),
            'median': round(statistics.median(prices), 2), 'highest': round(max(prices), 2)}
