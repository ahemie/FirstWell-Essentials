
import os
import sys
from pathlib import Path
from collections import Counter, defaultdict

from dotenv import load_dotenv
from supabase import create_client
from process_month import read_inventory, parse_links

BASE = Path(__file__).resolve().parent.parent
REPORT = BASE / "source_reports" / "Inventory Report.xlsx"
OBSERVED_ON = "2026-10-01"

load_dotenv(BASE / ".env")


def clean_id(value):
    text = str(value).strip()
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    return text


def connect():
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

    if not url or not key:
        raise RuntimeError("Missing Supabase .env credentials")

    return create_client(url, key)


def fetch_all(db, table, columns):
    result = []
    offset = 0

    while True:
        batch = (
            db.table(table)
            .select(columns)
            .range(offset, offset + 499)
            .execute()
            .data or []
        )

        result.extend(batch)

        if len(batch) < 500:
            break

        offset += 500

    return result


def main():
    if not REPORT.is_file():
        raise FileNotFoundError(REPORT)

    inventory, batches, report_date = read_inventory(
        str(REPORT)
    )

    links = []
    seen = set()
    duplicates = 0
    missing_avixo_ids = 0

    for product in inventory:
        avixo_id = clean_id(product.get("id"))

        if not avixo_id or avixo_id.lower() == "none":
            missing_avixo_ids += 1
            continue

        for market, item, variation in parse_links(
            product.get("comments")
        ):
            market = market.upper()
            item = clean_id(item)
            variation = clean_id(variation or "0")

            if market not in ("MY", "SG"):
                continue

            if not item:
                continue

            key = (avixo_id, market, item, variation)

            if key in seen:
                duplicates += 1
                continue

            seen.add(key)

            links.append({
                "avixo_id": avixo_id,
                "marketplace": market,
                "shopee_item_id": item,
                "shopee_variation_id": variation
            })

    print("\nFIRSTSTEP SHOPEE LINK IMPORT")
    print("--------------------------------")
    print("Inventory products:", len(inventory))
    print("Unique links:", len(links))
    print("MY links:", sum(
        x["marketplace"] == "MY" for x in links
    ))
    print("SG links:", sum(
        x["marketplace"] == "SG" for x in links
    ))
    print("Duplicate input links:", duplicates)
    print("Products missing Avixo IDs:", missing_avixo_ids)

    if missing_avixo_ids:
        print(
            "\nNote: Products without Avixo IDs "
            "cannot be linked."
        )

    # Detect conflicting mappings for the exact
    # same marketplace + item + variation.
    ownership = defaultdict(set)

    for link in links:
        key = (
            link["marketplace"],
            link["shopee_item_id"],
            link["shopee_variation_id"]
        )
        ownership[key].add(link["avixo_id"])

    conflicts = {
        key: owners
        for key, owners in ownership.items()
        if len(owners) > 1
    }

    if conflicts:
        print("\nCONFLICTING LINKS:")
        for key, owners in list(conflicts.items())[:10]:
            print(key, "Avixo:", sorted(owners))

        raise RuntimeError(
            "Resolve conflicting links before importing."
        )

    # Check Supabase product IDs.
    db = connect()

    products = fetch_all(
        db, "products", "id,avixo_id"
    )

    product_lookup = {
        clean_id(p["avixo_id"]): p["id"]
        for p in products
        if p.get("avixo_id") is not None
    }

    missing_products = sorted({
        link["avixo_id"]
        for link in links
        if link["avixo_id"] not in product_lookup
    })

    if missing_products:
        print("\nAvixo IDs missing from Supabase:")
        print(missing_products[:20])

        raise RuntimeError(
            "Some linked products do not exist "
            "in Supabase. No changes made."
        )

    # Check mappings already present.
    existing = fetch_all(
        db,
        "product_channel_links",
        "product_id,observed_on,marketplace,"
        "shopee_item_id,shopee_variation_id"
    )

    existing_keys = {
        (
            x["product_id"],
            x["observed_on"],
            x["marketplace"],
            x["shopee_item_id"],
            x["shopee_variation_id"]
        )
        for x in existing
    }

    records = []
    for link in links:
        record = {
            "product_id": product_lookup[
                link["avixo_id"]
            ],
            "observed_on": OBSERVED_ON,
            "marketplace": link["marketplace"],
            "shopee_item_id": link["shopee_item_id"],
            "shopee_variation_id": link[
                "shopee_variation_id"
            ]
        }

        key = (
            record["product_id"],
            record["observed_on"],
            record["marketplace"],
            record["shopee_item_id"],
            record["shopee_variation_id"]
        )

        if key not in existing_keys:
            records.append(record)

    print("\nSupabase products found:", len(products))
    print("Existing link records:", len(existing))
    print("New links to import:", len(records))
    print("Snapshot date:", OBSERVED_ON)

    # Preview is the default.
    if "--apply" not in sys.argv:
        print("\nPREVIEW ONLY.")
        print("No database changes.")
        print("\nAfter verification, run:")
        print("py import_shopee_links.py --apply")
        return

    # Insert links, without changing Shopee sales.
    for start in range(0, len(records), 100):
        batch = records[start:start + 100]

        db.table("product_channel_links").insert(
            batch
        ).execute()

        print(
            "Saved",
            min(start + 100, len(records)),
            "/",
            len(records)
        )

    print("\nSUCCESS!")
    print("Shopee product links imported.")
    print("Monthly Shopee sales were not modified.")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("\nSTOP:", error)
        sys.exit(1)
