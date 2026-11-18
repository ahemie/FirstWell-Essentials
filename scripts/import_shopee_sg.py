
import hashlib
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client

from process_month import read_shopee_perf

# ----------------------------------------
# 1. Project settings
# ----------------------------------------

BASE = Path(__file__).resolve().parent.parent
REPORT_DIR = BASE / "source_reports"

load_dotenv(BASE / ".env")

FILES = {
    "2026-07": "parentskudetail_July_SG.xlsx",
    "2026-08": "parentskudetail_August_SG.xlsx",
    "2026-09": "parentskudetail_September_SG.xlsx",
}

UNITS_COLUMN = "Units (Paid Order)"
SALES_COLUMN = "Sales (Paid Order) (SGD)"


# ----------------------------------------
# 2. Clean Shopee item ID
# ----------------------------------------

def clean_id(value):
    text = str(value).strip()

    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]

    return text


# ----------------------------------------
# 3. Read one Excel report
# ----------------------------------------

def read_month(month, filename):
    path = REPORT_DIR / filename

    if not path.is_file():
        raise FileNotFoundError(
            f"File not found: {path}"
        )

    parent, variations = read_shopee_perf(
        str(path),
        UNITS_COLUMN,
        SALES_COLUMN
    )

    items = {}

    # Parent totals include variation sales.
    # Never add parent and variation totals together.

    for item_id, info in parent.items():
        item_id = clean_id(item_id)

        items[item_id] = {
            "name": str(info.get("name") or ""),
            "units": float(info.get("units") or 0),
            "sales": float(info.get("sales") or 0)
        }

    # Aggregate variations only when the parent
    # record is missing.

    for (item_id, variation_id), info in variations.items():
        item_id = clean_id(item_id)

        if item_id in items:
            continue

        items[item_id] = {
            "name": "",
            "units": 0.0,
            "sales": 0.0
        }

        # Add all variations of this missing parent.
        for (other_id, other_var), v in variations.items():
            if clean_id(other_id) == item_id:
                items[item_id]["units"] += float(
                    v.get("units") or 0
                )
                items[item_id]["sales"] += float(
                    v.get("sales") or 0
                )

    records = []

    for item_id, info in items.items():
        records.append({
            "report_month": month + "-01",
            "marketplace": "SG",
            "shopee_item_id": item_id,
            "name_in_report": info["name"],
            "units_sold": info["units"],
            "sales_amount": round(info["sales"], 2),
            "currency": "SGD",
            "product_id": None,
            "mapping_status": "unmapped"
        })

    records.sort(
        key=lambda row: row["shopee_item_id"]
    )

    return path, records


# ----------------------------------------
# 4. Preview sales totals
# ----------------------------------------

def preview(months):
    print("\nFIRSTSTEP SHOPEE SG SALES IMPORT")
    print("----------------------------------")

    for month, path, records in months:
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
        print("Revenue SGD:", round(revenue, 2))
        print(
            "Average price/unit SGD:",
            round(average_price, 2)
        )

    print("\nProduct mappings: Pending")


# ----------------------------------------
# 5. Connect to Supabase
# ----------------------------------------

def connect():
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

    if not url or not key:
        sys.exit(
            "Missing Supabase credentials in .env"
        )

    return create_client(url, key)


# ----------------------------------------
# 6. Import one month safely
# ----------------------------------------

def import_month(db, month, path, records):
    print(f"\nImporting {month}...")

    file_hash = hashlib.sha256(
        b"shopee-sg-performance:"
        + path.read_bytes()
    ).hexdigest()

    existing = (
        db.table("report_imports")
        .select("id,status")
        .eq("sha256", file_hash)
        .execute()
        .data or []
    )

    if existing:
        import_id = existing[0]["id"]

        if existing[0]["status"] == "imported":
            print("Already imported. Skipped.")
            return

    else:
        # Prevent mixing different report versions.
        previous = (
            db.table("shopee_sales_monthly")
            .select("id")
            .eq("report_month", month + "-01")
            .eq("marketplace", "SG")
            .limit(1)
            .execute()
            .data or []
        )

        if previous:
            raise RuntimeError(
                f"SG data already exists for {month}. "
                "Review the existing import first."
            )

        response = (
            db.table("report_imports")
            .insert({
                "kind": "sgPerf",
                "reporting_month": month + "-01",
                "original_filename": path.name,
                "sha256": file_hash,
                "status": "pending",
                "source_row_count": len(records),
                "warning_count": 0
            })
            .execute()
        )

        import_id = response.data[0]["id"]

    # Fetch previously inserted rows in case
    # an earlier import stopped halfway through.
    saved_ids = set()
    start = 0

    while True:
        response = (
            db.table("shopee_sales_monthly")
            .select("shopee_item_id")
            .eq("import_id", import_id)
            .range(start, start + 499)
            .execute()
        )

        rows = response.data or []

        for row in rows:
            saved_ids.add(row["shopee_item_id"])

        if len(rows) < 500:
            break

        start += 500

    remaining = [
        {
            **record,
            "import_id": import_id
        }
        for record in records
        if record["shopee_item_id"] not in saved_ids
    ]

    # Save rows in batches of 100.
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

    db.table("report_imports").update({
        "status": "imported"
    }).eq("id", import_id).execute()

    print(f"{month}: Import completed.")


# ----------------------------------------
# 7. Main program
# ----------------------------------------

def main():
    months = []

    for month, filename in FILES.items():
        path, records = read_month(
            month, filename
        )

        months.append(
            (month, path, records)
        )

    preview(months)

    # Default = preview only.
    if "--apply" not in sys.argv:
        print("\nPREVIEW ONLY.")
        print("Nothing imported into Supabase.")

        print("\nTo import after verification:")
        print("py import_shopee_sg.py --apply")
        return

    db = connect()

    for month, path, records in months:
        import_month(
            db, month, path, records
        )

    print("\nALL SHOPEE SG IMPORTS COMPLETED!")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("\nSTOP:", error)
        print("Do not manually delete any records.")
        sys.exit(1)
