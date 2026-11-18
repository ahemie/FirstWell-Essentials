"""Run: python3 tests/test_link_match.py — strict name matcher must not confuse look-alike products."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend.link_match import pick
P = [dict(id=i, name=n) for i, n in enumerate([
    'FRISOLAC AR 400g', 'FRISOLAC HA 400g', 'Ceravis C+ Skin Barrier Repair Cream 100g', 'Ceravis M+ (menthol) cream 100g',
    'NAN HA 0-12 months 400g', 'NAN Lactose free 0-12 months 400g', 'Benzac Moderate Acne gel 5% 15g', 'Benzac Moderate Acne gel 5% 60g'])]
name = lambda r: r and r['name']
assert name(pick('Frisolac AR Special Formula 0–12 Months 400g | AR', '', P)[0]) == 'FRISOLAC AR 400g'
assert name(pick('FRISOLAC HA 400g | Hypoallergenic Infant Formula', '', P)[0]) == 'FRISOLAC HA 400g'
assert name(pick('CERAVIS M+ Skin Barrier Repair Cream 100 | EXP: 05/2029', '', P)[0]) != 'Ceravis C+ Skin Barrier Repair Cream 100g'
assert name(pick('Nestle NAN H.A.® Infant Formula Step 1 400g | 0–12', '', P)[0]) == 'NAN HA 0-12 months 400g'
assert name(pick('BENZAC Moderate Acne Gel 5% | 15g / 60g', '60g', P)[0]) == 'Benzac Moderate Acne gel 5% 60g'
assert pick('Friso Gold 30g Trial Pack | Step 3', '', P)[0] is None
print('PASS: strict matcher')
