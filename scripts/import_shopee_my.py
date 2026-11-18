
import hashlib
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client

# Reuse the Shopee Excel reader from your existing project
from process_month import read_shopee_perf

# ----------------------------------------
# 1. Project settings
# ----------------------------------------

BASE = Path(__file__).resolve().parent.parent
REPORT_DIR = BASE / "source_reports"

load_dotenv(BASE / ".env")

FILES = {
    "2026-07": "parentskudetail_July_MY.xlsx",
    "2026-08": "parentskudetail_August_MY.xlsx",
    "2026-09": "parentskudetail_September_MY.xlsx",
}

UNITS_COLUMN = "Units (Confirmed Order)"
SALES_COLUMN = "Sales (Confirmed Order) (MYR)"


# ----------------------------------------
# 2. Helper: Clean Shopee Item IDs
# ----------------------------------------

def clean_id(value):
    text = str(value).strip()

    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]

    return text


# ----------------------------------------
# 3. Read one month's Shopee MY Excel
# ----------------------------------------

def read_month(month, filename):
    path = REPORT_DIR / filename

    if not path.is_file():
        raise FileNotFoundError(
            f"Missing file: {path}"
        )

    parent, variations = read_shopee_perf(
        str(path),
        UNITS_COLUMN,
        SALES_COLUMN
    )

    items = {}

    # Use parent-level totals when available.
    # Parent totals already include their variations,
    # so we must not add variation totals again.

    for item_id, info in parent.items():
        key = clean_id(item_id)

        items[key] = {
            "name": str(info.get("name") or ""),
            "units": float(info.get("units") or 0),
            "sales": float(info.get("sales") or 0),
        }

    # If a parent row is missing, aggregate its
    # variation records instead.

    for (item_id, variation_id), info in variations.items():
        key = clean_id(item_id)

        if key in parent:
            continue

        if key not in items:
            items[key] = {
                "name": "",
                "units": 0.0,
                "sales": 0.0,
            }

        items[key]["units"] += float(
            info.get("units") or 0
        )

        items[key]["sales"] += float(
            info.get("sales") or 0
        )

    records = []

    for item_id, info in items.items():
        records.append({
            "report_month": month + "-01",
            "marketplace": "MY",
            "shopee_item_id": item_id,
            "name_in_report": info["name"],
            "units_sold": info["units"],
            "sales_amount": round(info["sales"], 2),
            "currency": "MYR",
            "product_id": None,
            "mapping_status": "unmapped",
        })

    records.sort(
        key=lambda row: row["shopee_item_id"]
    )

    return path, records


# ----------------------------------------
# 4. Preview all months
# ----------------------------------------

def preview(all_months):
    print("\nFIRSTSTEP SHOPEE MY SALES IMPORT")
    print("----------------------------------")

    for month, path, records in all_months:
        units = sum(
            row["units_sold"] for row in records
        )

        revenue = sum(
            row["sales_amount"] for row in records
        )

        average_price = (
            revenue / units if units else 0
        )

        print(f"\nMonth: {month}")
        print("File:", path.name)
        print("Shopee items:", len(records))
        print("Units sold:", round(units, 2))
        print("Revenue RM:", round(revenue, 2))
        print(
            "Average sales price/unit RM:",
            round(average_price, 2)
        )

    print("\nProduct mappings: Pending")
    print("No database changes during preview.")


# ----------------------------------------
# 5. Connect to Supabase
# ----------------------------------------

def connect():
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

    if not url or not key:
        sys.exit(
            "ERROR: Missing Supabase credentials."
        )

    return create_client(url, key)


# ----------------------------------------
# 6. Import one reporting month
# ----------------------------------------

def import_month(db, month, path, records):
    print(f"\nImporting {month}...")

    source_hash = hashlib.sha256(
        b"shopee-my-performance:"
        + path.read_bytes()
    ).hexdigest()

    existing_imports = (
        db.table("report_imports")
        .select("id,status")
        .eq("sha256", source_hash)
        .execute()
        .data or []
    )

    if existing_imports:
        import_id = existing_imports[0]["id"]

        if existing_imports[0]["status"] == "imported":
            print("Already imported. Skipped.")
            return

    else:
        # Prevent accidentally mixing two versions
        # of the same month's report.

        previous = (
            db.table("shopee_sales_monthly")
            .select("id")
            .eq("report_month", month + "-01")
            .eq("marketplace", "MY")
            .limit(1)
            .execute()
            .data or []
        )

        if previous:
            raise RuntimeError(
                f"{month} already has Shopee MY data. "
                "Review existing records first."
            )

        created = (
            db.table("report_imports")
            .insert({
                "kind": "myPerf",
                "reporting_month": month + "-01",
                "original_filename": path.name,
                "sha256": source_hash,
                "status": "pending",
                "source_row_count": len(records),
                "warning_count": 0,
            })
            .execute()
        )

        import_id = created.data[0]["id"]

    # Find already inserted rows.
    # This supports retrying interrupted imports.

    existing_ids = set()
    start = 0

    while True:
        found = (
            db.table("shopee_sales_monthly")
            .select("shopee_item_id")
            .eq("import_id", import_id)
            .range(start, start + 499)
            .execute()
            .data or []
        )

        for row in found:
            existing_ids.add(row["shopee_item_id"])

        if len(found) < 500:
            break

        start += 500

    remaining = []

    for record in records:
        if record["shopee_item_id"] in existing_ids:
            continue

        remaining.append({
            **record,
            "import_id": import_id
        })

    # Save in batches of 100

    for start in range(0, len(remaining), 100):
        batch = remaining[start:start + 100]

        db.table("shopee_sales_monthly").insert(
            batch
        ).execute()

        print(
            "Saved",
            min(start + 100, len(remaining)),
            "/",
            len(remaining)
        )

    # Mark import as completed

    db.table("report_imports").update({
        "status": "imported"
    }).eq("id", import_id).execute()

    print(f"{month}: Import completed.")


# ----------------------------------------
# 7. Main program
# ----------------------------------------

def main():
    all_months = []

    # Read all 3 Excel files

    for month, filename in FILES.items():
        path, records = read_month(
            month,
            filename
        )

        all_months.append(
            (month, path, records)
        )

    # Show report totals

    preview(all_months)

    # Safe default: preview only

    if "--apply" not in sys.argv:
        print("\nPREVIEW ONLY.")
        print("Nothing imported into Supabase.")

        print("\nTo import after verification:")
        print("py import_shopee_my.py --apply")
        return

    # Connect and save records

    db = connect()

    for month, path, records in all_months:
        import_month(
            db,
            month,
            path,
            records
        )

    print("\nALL SHOPEE MY IMPORTS COMPLETED!")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("\nSTOP:", error)
        print("No manual deletion is required.")
        sys.exit(1)
