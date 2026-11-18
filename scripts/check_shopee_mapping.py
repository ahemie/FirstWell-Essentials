
from pathlib import Path
from collections import Counter

from process_month import read_inventory, parse_links

BASE = Path(__file__).resolve().parent.parent
REPORT = BASE / "source_reports" / "Inventory Report.xlsx"

products, batches, report_date = read_inventory(str(REPORT))

links = []
missing = []
seen = Counter()

for product in products:
    avixo_id = product.get("id")
    name = product.get("name")
    comments = product.get("comments")

    product_links = parse_links(comments)

    if not product_links:
        missing.append(name)
        continue

    for marketplace, item_id, variation_id in product_links:
        if marketplace not in ("MY", "SG"):
            continue

        key = (marketplace, item_id, variation_id)
        seen[key] += 1

        links.append({
            "avixo_id": avixo_id,
            "product": name,
            "marketplace": marketplace,
            "item_id": item_id,
            "variation_id": variation_id
        })

shared = [
    key for key, count in seen.items()
    if count > 1
]

print("\nFIRSTSTEP SHOPEE PRODUCT MATCHING")
print("----------------------------------")
print("Avixo products:", len(products))
print("Total Shopee links:", len(links))

print(
    "Shopee MY links:",
    sum(x["marketplace"] == "MY" for x in links)
)

print(
    "Shopee SG links:",
    sum(x["marketplace"] == "SG" for x in links)
)

print("Products without Shopee links:", len(missing))
print("Shared/duplicate links:", len(shared))

print("\nFirst 10 links:")
for link in links[:10]:
    print(
        link["marketplace"],
        "Avixo:", link["avixo_id"],
        "Shopee:", link["item_id"],
        "Variation:", link["variation_id"]
    )

print("\nPREVIEW ONLY. No Supabase changes.")
