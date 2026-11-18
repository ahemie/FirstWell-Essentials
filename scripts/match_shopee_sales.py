
import os
import sys
from pathlib import Path
from collections import defaultdict, Counter

from dotenv import load_dotenv
from supabase import create_client

# ----------------------------------------
# 1. Settings
# ----------------------------------------

BASE = Path(__file__).resolve().parent.parent
load_dotenv(BASE / ".env")

# The mappings came from the inventory
# snapshot on October 1, 2026.
MAPPING_SNAPSHOT = "2026-10-01"

VALID_MONTHS = {
    "2026-07-01",
    "2026-08-01",
    "2026-09-01",
}

BATCH_SIZE = 500


# ----------------------------------------
# 2. Supabase connection
# ----------------------------------------

def connect():
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

    if not url or not key:
        raise RuntimeError(
            "Missing Supabase credentials in .env"
        )

    return create_client(url, key)


# ----------------------------------------
# 3. Fetch all database rows
# ----------------------------------------

def fetch_all(db, table, columns):
    records = []
    offset = 0

    while True:
        response = (
            db.table(table)
            .select(columns)
            .order("id")
            .range(offset, offset + BATCH_SIZE - 1)
            .execute()
        )

        batch = response.data or []
        records.extend(batch)

        if len(batch) < BATCH_SIZE:
            break

        offset += BATCH_SIZE

    return records


# ----------------------------------------
# 4. Clean Shopee identifiers
# ----------------------------------------

def clean_id(value):
    value = str(value).strip()

    if value.endswith(".0") and value[:-2].isdigit():
        value = value[:-2]

    return value


# ----------------------------------------
# 5. Build safe parent-only mappings
# ----------------------------------------

def build_mapping(links):
    # Each marketplace/item may have multiple
    # variation links pointing to different
    # Avixo products.

    grouped = defaultdict(list)

    for link in links:
        key = (
            link["marketplace"],
            clean_id(link["shopee_item_id"])
        )

        grouped[key].append(link)

    safe = {}
    variation_items = set()
    conflicting_items = set()

    for key, group in grouped.items():
        owners = {
            row["product_id"]
            for row in group
        }

        variation_ids = {
            clean_id(row["shopee_variation_id"])
            for row in group
        }

        # Parent-level mapping is safe only if:
        # 1. All links belong to one product.
        # 2. Every link uses variation ID 0.
        #
        # This prevents assigning a whole Shopee
        # listing to one product when variations
        # may represent different products.

        if variation_ids != {"0"}:
            variation_items.add(key)
            continue

        if len(owners) != 1:
            conflicting_items.add(key)
            continue

        safe[key] = next(iter(owners))

    return safe, variation_items, conflicting_items


# ----------------------------------------
# 6. Prepare monthly sales updates
# ----------------------------------------

def prepare_updates(sales, safe):
    updates = []
    stats = Counter()
    by_market = Counter()
    by_month = Counter()

    for row in sales:
        month = str(row["report_month"])
        market = row["marketplace"]

        if month not in VALID_MONTHS:
            stats["outside_scope"] += 1
            continue

        key = (
            market,
            clean_id(row["shopee_item_id"])
        )

        if key not in safe:
            stats["not_safe_to_match"] += 1
            continue

        target_product_id = safe[key]
        current_product_id = row.get("product_id")
        current_status = row.get("mapping_status")

        # Already matched correctly: no update.
        if (
            current_product_id == target_product_id
            and current_status == "matched"
        ):
            stats["already_matched"] += 1
            continue

        # Never overwrite an existing mapping,
        # even if the value looks incorrect.
        if (
            current_product_id is not None
            or current_status != "unmapped"
        ):
            stats["needs_manual_review"] += 1
            continue

        updates.append({
            "id": row["id"],
            "product_id": target_product_id,
            "marketplace": market,
            "report_month": month,
        })

        by_market[market] += 1
        by_month[(market, month)] += 1

    return updates, stats, by_market, by_month


# ----------------------------------------
# 7. Apply updates safely
# ----------------------------------------

def apply_updates(db, updates):
    total = len(updates)
    completed = 0

    for record in updates:
        # Update only the product link and status.
        #
        # units_sold and sales_amount are NEVER
        # modified.
        #
        # Conditional filters help prevent
        # overwriting rows that someone else
        # has already matched.

        response = (
            db.table("shopee_sales_monthly")
            .update({
                "product_id": record["product_id"],
                "mapping_status": "matched"
            })
            .eq("id", record["id"])
            .eq("marketplace", record["marketplace"])
            .eq("report_month", record["report_month"])
            .eq("mapping_status", "unmapped")
            .is_("product_id", "null")
            .execute()
        )

        completed += 1

        if completed % 100 == 0 or completed == total:
            print(
                f"Processed {completed} / {total}"
            )

    print("\nUpdate requests completed.")
    print(
        "Run the verification query to confirm "
        "the actual saved records."
    )


# ----------------------------------------
# 8. Main program
# ----------------------------------------

def main():
    print("\nFIRSTSTEP SHOPEE SALES MATCHING")
    print("--------------------------------")

    db = connect()

    links = fetch_all(
        db,
        "product_channel_links",
        "id,product_id,observed_on,marketplace,"
        "shopee_item_id,shopee_variation_id"
    )

    # Only use the known October snapshot.
    links = [
        row for row in links
        if str(row["observed_on"]) == MAPPING_SNAPSHOT
    ]

    sales = fetch_all(
        db,
        "shopee_sales_monthly",
        "id,report_month,marketplace,"
        "shopee_item_id,product_id,mapping_status"
    )

    safe, variations, conflicts = build_mapping(
        links
    )

    updates, stats, by_market, by_month = (
        prepare_updates(sales, safe)
    )

    print("Mapping snapshot:", MAPPING_SNAPSHOT)
    print("Saved product links:", len(links))
    print("Monthly sales records:", len(sales))
    print("Safe parent listings:", len(safe))
    print("Listings involving variations:", len(variations))
    print("Conflicting parent listings:", len(conflicts))

    print("\nSALES MATCHING PREVIEW")
    print("--------------------------------")

    print("Records ready to match:", len(updates))
    print(
        "Already matched:",
        stats["already_matched"]
    )
    print(
        "Variation/unmatched records:",
        stats["not_safe_to_match"]
    )
    print(
        "Existing mappings requiring review:",
        stats["needs_manual_review"]
    )

    print("\nUpdates by marketplace:")
    print("MY:", by_market["MY"])
    print("SG:", by_market["SG"])

    print("\nUpdates by month:")

    for market in ("MY", "SG"):
        for month in sorted(VALID_MONTHS):
            count = by_month[(market, month)]
            print(
                f"{market} {month[:7]}: {count}"
            )

    print("\nFirst 5 proposed matches:")

    for row in updates[:5]:
        print(
            "Sales ID:", row["id"],
            "| Product UUID:", row["product_id"]
        )

    if "--apply" not in sys.argv:
        print("\nPREVIEW ONLY.")
        print("No Supabase changes were made.")
        print("\nAfter verification, run:")
        print("py match_shopee_sales.py --apply")
        return

    if not updates:
        print("\nNothing new to match.")
        return

    print("\nUpdating Supabase...")
    apply_updates(db, updates)

    print("\nDONE.")
    print("Original sales figures were preserved.")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("\nSTOP:", error)
        sys.exit(1)
