# FirstWell Essentials — Inventory & Business Insights

A separate copy of the FirstStep dashboard (Dashboard · Price Watch · Inventory Update · Stock After Sales),
rebranded as **FirstWell Essentials**, with its **own Supabase project** and its **own Vercel project**.
It starts with **no data** — upload your FirstWell Essentials reports in *Upload Data*.

## 0. One-time setup (new Supabase + Vercel)

1. **Supabase** (project "FistWell Essentials") → SQL Editor → New query → paste `supabase/setup_new_project.sql` → Run.
2. Supabase → Authentication → Users → **Add user** (your admin email + password), then in SQL Editor:
   `insert into public.inv_staff (email, name, role) values ('your-admin@email.com', 'Admin', 'admin');`
3. **Vercel** → Add New → Project → import GitHub repo `ahemie/FirstWell-Essentials` → Framework: *Other* → add Environment Variables:

| Name | Where to find it |
|---|---|
| `SUPABASE_URL` | Supabase → Project Settings → API → Project URL |
| `SUPABASE_PUBLISHABLE_KEY` | Supabase → Project Settings → API Keys → publishable (or anon) key |
| `SUPABASE_SERVICE_ROLE_KEY` | Supabase → Project Settings → API Keys → secret / service_role key (**never share**) |
| `ALLOWED_EMAILS` | your admin email (comma-separated for more) |
| `APIFY_TOKEN` | only if you use Price Watch (can reuse the FirstStep Apify token) |

4. Deploy. Every push to `main` re-deploys automatically.
5. Logo: replace `assets/images/firstwell-essentials.png` with your real logo (same file name) whenever ready.

---


Five staff-only pages sharing one visual design, with a new **read-only Supabase BI** page and an existing **preview-first Supabase uploader**.

## 1. Start here (Windows PowerShell)

1. Extract this ZIP to a **new folder**, not over your previous working copy.
2. Copy `.env` from your existing project into **this folder beside `app.py`**. Never publish the `.env` file or any service role key.
3. Open PowerShell in the folder containing `manage.py`.
4. Run:

```powershell
py -m pip install -r requirements.txt
py manage.py serve
```

5. In your browser, sign in at **http://127.0.0.1:5503/login**. Open these staff-only pages:

| Page | Address | Data source |
|---|---|---|
| **Action Centre (new home)** | **`/overview.html`** | **Ranked reorder, expiry, idle-cash, pricing and data-fix lists; ABC concentration; channel and category scorecards; weekly sales trend; editable Shopee fee assumption** |
| Inventory | `/index.html` | Existing legacy JSON / JS |
| Business Analytics | `/analytics.html` | Existing legacy JSON / JS |
| Product Details | `/product.html` | Existing legacy JSON / JS |
| **Supabase BI (new)** | **`/bi.html`** | **Supabase reporting views and snapshots** |
| Upload Data | `/upload.html` | Supabase preview, conflict check, import and status |

Make sure **another Flask app is not already listening on port 5503**. Press Ctrl+C to stop the new server.

## The three sections

The site is split into three sections (switch between them with the bar under the header; defined once in `assets/js/nav.js`):

| # | Section | Pages | What it is for |
|---|---|---|---|
| 1 | **Dashboard** | Stock Report (`/index.html`), Business Analytics, Product Details, Live Sales, Action Centre, Upload Data | Reports, analytics and Excel uploads |
| 2 | **Price Scraping** | Price Watch (`/scrap.html`) | Competitor Shopee prices (Apify) |
| 3 | **Inventory Update** | Scan & Update (`/inventory.html`) | Staff scan a product barcode, then count stock, stock in or stock out |

To add or move a page, edit `SECTIONS` in `assets/js/nav.js`, add the file to the `allowed_pages` list in `app.py`, and put `<nav class="site-nav fs-nav"></nav><script src="/assets/js/nav.js"></script>` plus `data-page="..."` on the page. `node tests/nav.test.js` checks all of this.

### Inventory Update (section 3)

- Phone-first. Scan with a Bluetooth/USB scanner (types into the box), or tap **Camera** (live scan) or **Take photo** (one sharp picture, best for small or glossy barcodes) (works on Android Chrome and iPhone Safari; the site must be opened with https).
- **Count stock**: blind count by default (system quantity hidden), one line per expiry date, a reason is required for any difference, then **Save all counts**. The result screen lists only the products that differ from the system, with a CSV/print list for correcting **Avixo**.
- **Stock in / Stock out / Recent** (with Undo) use the existing Supabase `inv_*` functions (`inv_products`, `inv_count_many`, `inv_stock_in`, `inv_stock_out`, `inv_barcode_link`, `inv_history`, `inv_undo`).
- First scan of an unknown barcode: pick the product once and the barcode is remembered for everyone (`inv_barcodes`).
- Sign-in: this page signs in to Supabase Auth itself (same email/password), because the `inv_*` functions check the person against `inv_staff`. The email must be in `inv_staff` (Authentication > Users + `inv_staff` row). Needs `SUPABASE_URL` and `SUPABASE_PUBLISHABLE_KEY` on the server; the page gets them from `/api/inv/config` (publishable key only, never a secret).

## Price Watch (competitor Shopee prices)

The former FirstStep-Scrap app now lives inside this dashboard at **`/scrap.html`** (nav item "Price Watch").
It uses the same staff login as every other page. Code: `backend/scrap_api.py` (routes under `/api/scrap/*`),
`backend/scrap_lib/` (matching helpers and the bundled own-product catalogue), `assets/js/scrap.js`, `assets/css/scrap.css`.

Tables (same Supabase project): `fs_competitor_*`, `fs_scrape_runs`, `fs_scrape_results`, `fs_link_checks`.

Extra environment variables needed for scraping (set in `.env` locally and in Vercel; never commit them):
`APIFY_TOKEN` (required), and optionally `APIFY_ACTOR_ID`, `MAX_CHARGE_PER_RUN_USD`, `SEARCH_CANDIDATES_PER_RUN`,
`MAX_RESULTS_PER_PRODUCT`, `OWN_SHOP_IDS`, `APIFY_TIMEOUT_SECS`, `SCRAPE_SORT`.

Tests: `python -m unittest discover -s tests/scrap -t .`

## 2. Organized source folders

```text
FirstStep_Supabase_Protected/
├── app.py                   Flask app, staff login, APIs and page routing
├── manage.py                Friendly launcher (`py manage.py serve`)
├── process_month.py         Shared Excel parsing code (imported by app.py and backend/)
├── requirements.txt
├── vercel.json
│
├── pages/                   Every HTML page; still opened at /<name>.html
│   ├── overview.html        Action Centre (home page, /)
│   ├── index.html           Stock Report
│   ├── analytics.html       Business Analytics
│   ├── product.html         Product Details
│   ├── bi.html              Supabase BI
│   ├── upload.html          Upload Data (Excel + weekly sales)
│   ├── scrap.html           Price Watch
│   ├── inventory.html       Scan & Update
│   └── stock-after-sales.html  Stock After Sales
│
├── assets/
│   ├── css/                 One stylesheet per page, plus shell.css (shared header/nav)
│   ├── js/                  One script per page, plus nav.js and auth-ui.js (sign-out)
│   ├── images/
│   └── vendor/              Third-party libraries (barcode scanner)
│
├── backend/                 API modules registered by app.py (BI, scrap, stock, weekly sales, upload)
├── scripts/                 Historical one-off import tools (see below)
├── supabase/migrations/     Database migrations
├── tests/                   JS (node) and Python (unittest) tests
├── samples/                 Static one-off pages, not served by the app
├── docs/                    Installation, data notes, architectural guide
├── source_reports/          Original reports (local only, git-ignored)
└── data/                    Legacy JSON and JS snapshots (local only, git-ignored)
```

### Where to edit what

- Change **menu, header or shared colors**: `assets/css/shell.css`, then add the page to `assets/js/nav.js` and to the allowed pages in `app.py`.
- Change **Upload layout**: `pages/upload.html`.
- Change **Upload styles**: `assets/css/upload.css`.
- Change **Upload interactions**: `assets/js/upload.js`.
- Change **Upload parsing/saving**: `backend/supabase_upload.py`.
- Change **BI layout**: `pages/bi.html`.
- Change **BI charts/KPIs/tables**: `assets/js/bi.js` and `assets/css/bi.css`.
- Change **BI database retrieval**: `backend/bi_api.py`.
- Change authentication or root Flask routing: `app.py`.

## 3. Supabase BI: metric definitions

BI is **read-only**; it makes no changes to Supabase.

- Monthly revenue and counts: `v_channel_monthly_summary`.
- Shopee top products: `v_shopee_sales_clean`, joined to `products` only where a verified `product_id` exists. This avoids adding variation and parent sales together.
- Stock summary: `v_inventory_latest_summary` and latest `inventory_snapshots`.
- Pricing snapshots: `listing_price_snapshots`, latest snapshot per marketplace.
- Source history: `report_imports`.
- Clinic revenue is **estimated** (`units_sold × clinic price`), not cashier receipts.
- Shopee MY amounts are **MYR**; Shopee SG amounts are **SGD**. BI never adds the two currencies together.
- Stock is an inventory **snapshot**, not a live available quantity. The BI low-stock threshold is 5 units, for review only.
- The date filters apply to monthly sales, charts and top products. Stock, listing prices and import history always refer to their latest available snapshots/history (independent of the selected sales period).
- CSV export is on the BI page. It exports the filtered monthly channel summary.

### Database tables/views required

`products`, `inventory_snapshots`, `listing_price_snapshots`, `report_imports`, `v_channel_monthly_summary`, `v_inventory_latest_summary`, `v_shopee_sales_clean`. These are already present in your existing FirstStep Supabase project; **no SQL migrations or table deletions** are required.

## 4. Upload & safety

1. Upload one original `.xlsx` file (CSV is not supported in the new Supabase uploader).
2. Choose a month (for price reports also a snapshot/export date).
3. **Preview**. The server compares against the existing Supabase records.
4. Import only after reviewing source month, warnings, new / identical / changed / missing counts.
5. Changed or missing records conflict; the uploader blocks silent replacement. Previously imported identical data is skipped.
6. Some accepted imports run in batches rather than atomically. On error, stop, preserve the log and investigate; do not delete records by hand.

SG prices are **not automatically imported**. Wait until your team approves the revised SG Excel export.

For a harmless first test, preview `source_reports/mass_update_MY.xlsx` with report type **MY Listing Prices**, month **2026-10**, snapshot date **2026-10-10**. The expected result is 574 identical rows, 0 new rows, provided the live database still contains the earlier successful import. Do **not** accept if the preview reports conflicts.

## 5. Historical importer commands

The original one-off scripts are now in `scripts/`. Start each with **`-m`**, so it still finds `process_month.py` and the project-root `.env`:

```powershell
py -m scripts.import_shopee_my_prices
py -m scripts.import_shopee_my_prices --apply
py -m scripts.check_shopee_mapping
```

For convenience, also use:

```powershell
py manage.py list
py manage.py my-prices
py manage.py my-prices --apply
```

**Do not run historical import tools with `--apply` unless you specifically intend to change saved data**. Other older scripts may write without a separate preview; inspect them first. They were reorganized and their base file paths updated, not redesigned.

## 6. Secrets / rollback / validation

- `.env` stays in the **project root**; service role credentials remain **server-only**.
- The Flask login continues to protect all HTML and API paths using your existing Supabase staff authentication and CSRF checks.
- No database, Supabase records or live data were deleted or modified to prepare this ZIP.
- Keep your original copy. If anything fails, stop the new Flask instance and run the old project as before.
- Syntax and report-format detection checks were performed, but **full browser-to-live-Supabase import testing was not performed**. Test pages with your own server before accepting new uploads.
