
import hashlib
import os
import sys
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client
from process_month import read_shopee_price


# ----------------------------------------
# 1. SETTINGS
# ----------------------------------------

BASE = Path(__file__).resolve().parent.parent

FILE = BASE / "source_reports" / "mass_update_MY.xlsx"

MARKETPLACE = "MY"
CURRENCY = "MYR"
SNAPSHOT_DATE = "2026-10-10"
REPORT_MONTH = "2026-10-01"

load_dotenv(BASE / ".env")


# ----------------------------------------
# 2. HELPER FUNCTIONS
# ----------------------------------------

def clean_id(value):
    text = str(value).strip()

    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]

    return text


def money(value):
    return Decimal(str(value)).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP
    )


def connect():
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

    if not url or not key:
        raise RuntimeError(
            "Missing Supabase credentials in .env"
        )

    return create_client(url, key)


# ----------------------------------------
# 3. READ SHOPEE MY EXCEL
# ----------------------------------------

def read_prices():
    if not FILE.is_file():
        raise FileNotFoundError(
            f"File not found: {FILE}"
        )

    prices, by_item = read_shopee_price(str(FILE))

    records = []
    seen = set()

    for (item_id, variation_id), price in prices.items():

        item_id = clean_id(item_id)
        variation_id = clean_id(variation_id or "0")

        if not item_id or item_id.lower() == "none":
            raise ValueError("Missing Shopee Product ID")

        if not item_id.isdigit() or not variation_id.isdigit():
            raise ValueError(
                f"Invalid Shopee IDs: {item_id}, {variation_id}"
            )

        if price is None:
            raise ValueError(
                f"Missing price: {item_id}/{variation_id}"
            )

        value = money(price)

        if not value.is_finite() or value <= 0:
            raise ValueError(
                f"Invalid price for {item_id}/{variation_id}"
            )

        key = (item_id, variation_id)

        if key in seen:
            raise ValueError(
                f"Duplicate listing: {key}"
            )

        seen.add(key)

        records.append({
            "marketplace": MARKETPLACE,
            "shopee_item_id": item_id,
            "shopee_variation_id": variation_id,
            "snapshot_date": SNAPSHOT_DATE,
            "listed_price": str(value),
            "currency": CURRENCY
        })

    records.sort(
        key=lambda r: (
            r["shopee_item_id"],
            r["shopee_variation_id"]
        )
    )

    if not records:
        raise ValueError("No usable MY prices found")

    return records


# ----------------------------------------
# 4. DISPLAY PREVIEW
# ----------------------------------------

def preview(records):
    print("\nFIRSTSTEP SHOPEE MY PRICE IMPORT")
    print("--------------------------------")

    prices = [
        Decimal(r["listed_price"])
        for r in records
    ]

    print("File:", FILE.name)
    print("Marketplace:", MARKETPLACE)
    print("Currency:", CURRENCY)
    print("Snapshot date:", SNAPSHOT_DATE)
    print("Total price records:", len(records))
    print(
        "Unique Shopee items:",
        len({r["shopee_item_id"] for r in records})
    )
    print("Minimum price RM:", min(prices))
    print("Maximum price RM:", max(prices))

    print("\nFirst 5 records:")

    for row in records[:5]:
        print(
            row["shopee_item_id"],
            "| Variation:",
            row["shopee_variation_id"],
            "| RM",
            row["listed_price"]
        )


# ----------------------------------------
# 5. IMPORT PRICES INTO SUPABASE
# ----------------------------------------

def import_prices(db, records):

    file_hash = hashlib.sha256(
        b"shopee-my-prices:"
        + FILE.read_bytes()
    ).hexdigest()

    existing = (
        db.table("report_imports")
        .select("id,status")
        .eq("sha256", file_hash)
        .execute()
        .data or []
    )

    if existing and existing[0]["status"] == "imported":
        print("\nThis price file was already imported.")
        print("Nothing changed.")
        return

    # Check which rows already exist
    # for this MY price snapshot.

    saved = []
    offset = 0

    while True:
        batch = (
            db.table("listing_price_snapshots")
            .select(
                "marketplace,shopee_item_id,"
                "shopee_variation_id,snapshot_date,"
                "listed_price,import_id"
            )
            .eq("marketplace", MARKETPLACE)
            .eq("snapshot_date", SNAPSHOT_DATE)
            .range(offset, offset + 499)
            .execute()
            .data or []
        )

        saved.extend(batch)

        if len(batch) < 500:
            break

        offset += 500

    if not existing and saved:
        raise RuntimeError(
            "MY prices already exist for this date "
            "from another import. Review first."
        )

    import_id = (
        existing[0]["id"] if existing else None
    )

    if existing and existing[0]["status"] not in (
        "pending", "validated"
    ):
        raise RuntimeError(
            "Existing import requires manual review."
        )

    expected = {
        (
            r["shopee_item_id"],
            r["shopee_variation_id"]
        ): Decimal(r["listed_price"])
        for r in records
    }

    saved_keys = set()

    for row in saved:
        key = (
            row["shopee_item_id"],
            row["shopee_variation_id"]
        )

        if (
            row["import_id"] != import_id
            or key not in expected
            or Decimal(str(row["listed_price"])) != expected[key]
        ):
            raise RuntimeError(
                "Existing price row differs from this file. "
                "No further changes made."
            )

        saved_keys.add(key)

    # Create import history if this is a new file.

    if import_id is None:
        result = (
            db.table("report_imports")
            .insert({
                "kind": "myPrice",
                "reporting_month": REPORT_MONTH,
                "snapshot_date": SNAPSHOT_DATE,
                "original_filename": FILE.name,
                "sha256": file_hash,
                "status": "pending",
                "source_row_count": len(records),
                "warning_count": 0
            })
            .execute()
        )

        import_id = result.data[0]["id"]

    remaining = [
        {
            **row,
            "import_id": import_id
        }
        for row in records
        if (
            row["shopee_item_id"],
            row["shopee_variation_id"]
        ) not in saved_keys
    ]

    # Import in batches of 100.

    for start in range(0, len(remaining), 100):
        batch = remaining[start:start + 100]

        db.table("listing_price_snapshots").insert(
            batch
        ).execute()

        print(
            "Saved",
            min(start + 100, len(remaining)),
            "/",
            len(remaining)
        )

    # Mark the import as completed.

    db.table("report_imports").update({
        "status": "imported"
    }).eq("id", import_id).execute()

    print("\nSUCCESS!")
    print("Shopee MY listing prices imported.")
    print("Shopee SG data was not modified.")


# ----------------------------------------
# 6. MAIN PROGRAM
# ----------------------------------------

def main():
    records = read_prices()

    preview(records)

    if "--apply" not in sys.argv:
        print("\nPREVIEW ONLY.")
        print("No Supabase changes made.")
        print("\nAfter verification, run:")
        print("py import_shopee_my_prices.py --apply")
        return

    db = connect()
    import_prices(db, records)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("\nSTOP:", error)
        print("Do not manually delete database records.")
        sys.exit(1)
