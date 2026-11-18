
import hashlib
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client

# ----------------------------------------
# 1. Load September data
# ----------------------------------------
BASE = Path(__file__).resolve().parent.parent
DATA_FILE = BASE / "data" / "2026-09.json"

load_dotenv(BASE / ".env")

with DATA_FILE.open("r", encoding="utf-8") as f:
    data = json.load(f)

products = data["products"]
month = data["meta"]["month"]
report_month = month + "-01"

# Clinic revenue = units sold x clinic selling price
valid = [
    p for p in products
    if p.get("id") is not None
    and str(p.get("id")).strip()
    and (p.get("s") or 0) > 0
]

missing_id_sales = [
    p for p in products
    if not str(p.get("id") or "").strip()
    and (p.get("s") or 0) > 0
]

total_units = sum(p.get("s") or 0 for p in valid)
total_revenue = sum(
    (p.get("s") or 0) * (p.get("p") or 0)
    for p in valid
)

missing_price = [
    p for p in valid if not p.get("p")
]

ids = [str(p["id"]).strip() for p in valid]

print("\nFIRSTSTEP CLINIC SALES IMPORT")
print("--------------------------------")
print("Reporting month:", month)
print("Products with clinic sales:", len(valid))
print("Clinic units sold:", total_units)
print("Estimated revenue RM:", round(total_revenue, 2))
print("Sold products without IDs:", len(missing_id_sales))
print("Sold products without prices:", len(missing_price))

if len(ids) != len(set(ids)):
    sys.exit("STOP: Duplicate product IDs found.")

if missing_id_sales or missing_price:
    print("\nSTOP: Some sales cannot be safely imported.")
    for p in missing_id_sales:
        print("Missing ID:", p.get("n"))
    for p in missing_price:
        print("Missing price:", p.get("n"))
    sys.exit(1)

# ----------------------------------------
# 2. Preview only (safe default)
# ----------------------------------------
if "--apply" not in sys.argv:
    print("\nPREVIEW ONLY - No Supabase changes.")

    print("\nFirst 5 clinic sales records:")
    for p in valid[:5]:
        units = p.get("s") or 0
        price = p.get("p") or 0
        print(
            p["id"],
            p["n"],
            "Units:", units,
            "Price:", price,
            "Revenue:", round(units * price, 2)
        )

    print("\nTo import, run:")
    print("py import_clinic_sales.py --apply")
    sys.exit(0)

# ----------------------------------------
# 3. Connect to Supabase
# ----------------------------------------
url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

if not url or not key:
    sys.exit("Missing Supabase credentials in .env")

db = create_client(url, key)

# ----------------------------------------
# 4. Get existing products and their UUIDs
# ----------------------------------------
product_map = {}
start = 0

while True:
    response = (
        db.table("products")
        .select("id,avixo_id")
        .range(start, start + 499)
        .execute()
    )

    rows = response.data or []

    for row in rows:
        product_map[str(row["avixo_id"])] = row["id"]

    if len(rows) < 500:
        break

    start += 500

unmatched = [
    p for p in valid
    if str(p["id"]).strip() not in product_map
]

if unmatched:
    for p in unmatched:
        print("Not found in Supabase:", p["n"])
    sys.exit("STOP: Product matching failed.")

# ----------------------------------------
# 5. Create or reuse an import-history record
# ----------------------------------------
file_hash = hashlib.sha256(
    b"clinic-movement:" + DATA_FILE.read_bytes()
).hexdigest()

existing_import = (
    db.table("report_imports")
    .select("id,status")
    .eq("sha256", file_hash)
    .execute()
    .data
)

if existing_import:
    import_id = existing_import[0]["id"]

    if existing_import[0]["status"] == "imported":
        print("\nClinic sales file already imported.")
        print("No duplicate records created.")
        sys.exit(0)

else:
    # Avoid silently mixing different versions of
    # the same month's clinic sales.
    previous = (
        db.table("clinic_movement_monthly")
        .select("id")
        .eq("report_month", report_month)
        .limit(1)
        .execute()
        .data
    )

    if previous:
        sys.exit(
            "STOP: Clinic sales already exist for this month. "
            "Review the existing import before replacing it."
        )

    created = (
        db.table("report_imports")
        .insert({
            "kind": "movement",
            "reporting_month": report_month,
            "original_filename": DATA_FILE.name,
            "sha256": file_hash,
            "status": "pending",
            "source_row_count": len(valid),
            "warning_count": 0
        })
        .execute()
    )

    import_id = created.data[0]["id"]

# ----------------------------------------
# 6. Prepare sales rows
# ----------------------------------------
sales_rows = []

for p in valid:
    units = p.get("s") or 0
    price = p.get("p")

    sales_rows.append({
        "report_month": report_month,
        "avixo_name_in_report": p["n"],
        "product_id": product_map[str(p["id"]).strip()],
        "units_sold": units,
        "estimated_revenue_rm": round(units * price, 2),
        "price_snapshot_date": data["meta"]["today"],
        "import_id": import_id
    })

# ----------------------------------------
# 7. Save without duplicating on retry
# ----------------------------------------
try:
    existing_rows = (
        db.table("clinic_movement_monthly")
        .select("product_id")
        .eq("import_id", import_id)
        .execute()
        .data
    )

    existing_ids = {
        row["product_id"] for row in existing_rows
    }

    remaining = [
        row for row in sales_rows
        if row["product_id"] not in existing_ids
    ]

    for start in range(0, len(remaining), 100):
        batch = remaining[start:start + 100]

        db.table("clinic_movement_monthly").insert(
            batch
        ).execute()

        print(
            "Saved",
            min(start + 100, len(remaining)),
            "/",
            len(remaining),
            "remaining records"
        )

    db.table("report_imports").update({
        "status": "imported"
    }).eq("id", import_id).execute()

except Exception as error:
    print("\nIMPORT INCOMPLETE:", error)
    print("Do not delete any database records.")
    sys.exit(1)

print("\nSUCCESS!")
print("Clinic sales products:", len(sales_rows))
print("Total clinic units:", total_units)
print("Estimated revenue RM:", round(total_revenue, 2))
