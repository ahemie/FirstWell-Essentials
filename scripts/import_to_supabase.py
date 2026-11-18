
import json
import os
import sys
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client

# 1. Find the files
BASE_DIR = Path(__file__).resolve().parent.parent
JSON_FILE = BASE_DIR / "data" / "2026-09.json"

load_dotenv(BASE_DIR / ".env")

# 2. Read the September data
with open(JSON_FILE, "r", encoding="utf-8") as file:
    data = json.load(file)

products = data["products"]

# 3. Prepare products for the Supabase products table
valid_products = []
missing_ids = []

for product in products:
    product_id = product.get("id")

    if product_id is None or str(product_id).strip() == "":
        missing_ids.append(product.get("n", "Unknown"))
        continue

    valid_products.append({
        "avixo_id": str(product_id).strip(),
        "name": product.get("n") or "Unnamed product",
        "category": product.get("c") or "Uncategorised",
        "stock_unit": product.get("u")
    })

# 4. Check duplicate IDs before importing
id_counts = Counter(p["avixo_id"] for p in valid_products)
duplicates = [
    key for key, count in id_counts.items()
    if count > 1
]

print("\nFIRSTSTEP SEPTEMBER IMPORT")
print("--------------------------")
print("Total records:", len(products))
print("Valid product IDs:", len(valid_products))
print("Missing product IDs:", len(missing_ids))
print("Duplicate product IDs:", len(duplicates))

if missing_ids:
    print("\nProducts without IDs (will be skipped):")
    for name in missing_ids:
        print(" -", name)

if duplicates:
    print("\nERROR: Duplicate IDs detected:", duplicates)
    print("Import cancelled. Review the source data.")
    sys.exit(1)

# 5. PREVIEW MODE: default, no database changes
if "--apply" not in sys.argv:
    print("\nPREVIEW ONLY — nothing has been imported.")
    print("\nFirst 5 products:")
    for product in valid_products[:5]:
        print(product)

    print("\nWhen ready, run:")
    print("py import_to_supabase.py --apply")
    sys.exit(0)

# 6. Connect to Supabase only when applying
url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

if not url or not key or key == "PASTE_YOUR_SERVER_KEY_HERE":
    print("Missing Supabase URL or service role key in .env")
    sys.exit(1)

supabase = create_client(url, key)

# 7. Import products
# Upsert means:
# - Insert if the product ID is new
# - Update if that product ID already exists
# - Never create another row with the same Avixo ID
print("\nImporting products...")

batch_size = 100

try:
    for start in range(0, len(valid_products), batch_size):
        batch = valid_products[start:start + batch_size]

        supabase.table("products").upsert(
            batch,
            on_conflict="avixo_id"
        ).execute()

        print(f"Processed {start + len(batch)} / {len(valid_products)}")

except Exception as error:
    print("\nImport stopped:", error)
    print("Earlier batches may already have been saved.")
    print("After fixing the problem, rerun --apply safely.")
    sys.exit(1)

print("\nImport completed!")
print("Check your products table in Supabase.")
