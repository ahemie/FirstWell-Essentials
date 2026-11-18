
import json
import os
import sys
import hashlib
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client

# ----------------------------------------
# 1. Find your project files
# ----------------------------------------
BASE = Path(__file__).resolve().parent.parent
DATA_FILE = BASE / "data" / "2026-09.json"

load_dotenv(BASE / ".env")

with DATA_FILE.open("r", encoding="utf-8") as file:
    data = json.load(file)

products = data["products"]
month = data["meta"]["month"]
snapshot_date = data["meta"]["today"]

valid = [
    p for p in products
    if p.get("id") is not None
    and str(p.get("id")).strip() != ""
]

missing = len(products) - len(valid)
total_units = sum(p.get("q") or 0 for p in valid)
total_value = sum(p.get("val") or 0 for p in valid)
batch_count = sum(len(p.get("b") or []) for p in valid)

# ----------------------------------------
# 2. Preview the data
# ----------------------------------------
print("\nFIRSTSTEP INVENTORY IMPORT")
print("-----------------------------")
print("Reporting month:", month)
print("Stock snapshot date:", snapshot_date)
print("Products:", len(valid))
print("Missing IDs (skipped):", missing)
print("Stock units:", total_units)
print("Stock value RM:", round(total_value, 2))
print("Expiry batches:", batch_count)

ids = [str(p["id"]).strip() for p in valid]

if len(ids) != len(set(ids)):
    sys.exit("ERROR: Duplicate Avixo IDs found.")

if "--apply" not in sys.argv:
    print("\nPREVIEW ONLY. Supabase was NOT changed.")
    print("\nFirst 5 inventory records:")

    for p in valid[:5]:
        print(
            p["id"],
            p["n"],
            "Stock:", p.get("q", 0),
            "Cost:", p.get("lc"),
            "Batches:", len(p.get("b") or [])
        )

    print("\nTo import, run:")
    print("py import_inventory_to_supabase.py --apply")
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
# 4. Match Avixo IDs to Supabase UUIDs
# ----------------------------------------
product_map = {}

start = 0
page_size = 500

while True:
    response = (
        db.table("products")
        .select("id,avixo_id")
        .range(start, start + page_size - 1)
        .execute()
    )

    rows = response.data or []

    for row in rows:
        product_map[str(row["avixo_id"])] = row["id"]

    if len(rows) < page_size:
        break

    start += page_size

unmatched = [
    p["n"] for p in valid
    if str(p["id"]).strip() not in product_map
]

if unmatched:
    print("\nProducts not found in Supabase:")
    for name in unmatched:
        print("-", name)
    sys.exit("STOP: Product matching failed.")

# ----------------------------------------
# 5. Check import history
# ----------------------------------------
file_hash = hashlib.sha256(
    DATA_FILE.read_bytes()
).hexdigest()

existing = (
    db.table("report_imports")
    .select("id,status")
    .eq("sha256", file_hash)
    .execute()
    .data
)

if existing:
    import_id = existing[0]["id"]

    if existing[0]["status"] == "imported":
        print("\nThis file was already imported.")
        print("No duplicate records created.")
        sys.exit(0)

else:
    # Protect existing inventory from a different upload.
    existing_stock = (
        db.table("inventory_snapshots")
        .select("product_id")
        .eq("snapshot_date", snapshot_date)
        .limit(1)
        .execute()
        .data
    )

    if existing_stock:
        sys.exit(
            "STOP: This snapshot date already has inventory. "
            "Review it before importing another version."
        )

    created = (
        db.table("report_imports")
        .insert({
            "kind": "inventory",
            "reporting_month": month + "-01",
            "snapshot_date": snapshot_date,
            "original_filename": DATA_FILE.name,
            "sha256": file_hash,
            "status": "pending",
            "source_row_count": len(valid),
            "warning_count": missing
        })
        .execute()
    )

    import_id = created.data[0]["id"]

# ----------------------------------------
# 6. Prepare stock snapshots and batches
# ----------------------------------------
stock_rows = []
batch_rows = []

for p in valid:
    product_uuid = product_map[str(p["id"]).strip()]

    stock_rows.append({
        "product_id": product_uuid,
        "snapshot_date": snapshot_date,
        "quantity": p.get("q") or 0,
        "latest_cost_rm": p.get("lc"),
        "clinic_list_price_rm": p.get("p"),
        "stock_value_rm": p.get("val"),
        "summary_balance": p.get("qs"),
        "stock_unit": p.get("u"),
        "import_id": import_id
    })

    for number, batch in enumerate(p.get("b") or [], 1):
        expiry_date = batch[0]
        quantity = batch[1]

        batch_rows.append({
            "product_id": product_uuid,
            "snapshot_date": snapshot_date,
            "batch_number": number,
            "expiry_date": expiry_date or None,
            "quantity": quantity,
            "stock_cost_value_rm": (
                round(quantity * p["lc"], 2)
                if p.get("lc") is not None else None
            ),
            "stock_retail_value_rm": (
                round(quantity * p["p"], 2)
                if p.get("p") is not None else None
            ),
            "import_id": import_id
        })

# ----------------------------------------
# 7. Save in batches
# ----------------------------------------
def save_rows(table, rows, conflict_columns):
    batch_size = 100

    for start in range(0, len(rows), batch_size):
        batch = rows[start:start + batch_size]

        db.table(table).upsert(
            batch,
            on_conflict=conflict_columns
        ).execute()

        print(
            table,
            min(start + batch_size, len(rows)),
            "/",
            len(rows)
        )

try:
    print("\nSaving inventory snapshots...")

    save_rows(
        "inventory_snapshots",
        stock_rows,
        "product_id,snapshot_date"
    )

    print("\nSaving expiry batches...")

    save_rows(
        "inventory_batches",
        batch_rows,
        "product_id,snapshot_date,batch_number"
    )

    db.table("report_imports").update({
        "status": "imported"
    }).eq("id", import_id).execute()

except Exception as error:
    print("\nIMPORT INCOMPLETE:", error)
    print("Do not delete any rows manually.")
    print("After fixing the error, rerun --apply.")
    sys.exit(1)

print("\nSUCCESS!")
print("Inventory snapshots:", len(stock_rows))
print("Expiry batches:", len(batch_rows))
print("Snapshot date:", snapshot_date)
