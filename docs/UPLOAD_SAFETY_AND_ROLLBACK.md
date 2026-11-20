# FirstStep — Supabase Upload & Data Management upgrade

## Files changed
- `upload.html`: new staff upload interface. Calls new Supabase routes instead of local SQLite preview/accept.
- `supabase_upload.py`: new server-side upload API (`/api/supabase-upload/preview`, `/accept`, `/status`).
- `app.py`: your original Flask app plus one registration hook for `supabase_upload.py`. Existing authentication and local routes preserved.
- `requirements.txt`: dependencies used by the backend.

## Installation (Windows PowerShell)
1. **Back up your existing project folder.** Extract the ZIP to a **different folder** first. Never overwrite your existing `.env` or active `firstwell.db`.
2. Copy the existing local `.env` into the new project folder (never upload the secret or put it into HTML). Required variables: `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_PUBLISHABLE_KEY`, `ALLOWED_EMAILS`.
3. In VS Code PowerShell, enter the extracted `FirstStep_Supabase_Protected` folder.
4. Run `py -m pip install -r requirements.txt`.
5. If another Flask instance is running on 5503, stop that one first.
6. Start the upgraded app:
   `py -c "from app import app; app.run(host='127.0.0.1', port=5503, debug=False)"`
7. Visit `http://127.0.0.1:5503/login`, sign in, then open `http://127.0.0.1:5503/upload.html`.
8. Test **a previously imported** MY price report (month `2026-10`, snapshot `2026-10-10`, file `mass_update_MY.xlsx`). Preview should show `0 new` and `574 identical` and should NOT duplicate prices.
9. Test **a previously imported** July MY performance report (month `2026-07`). Existing parent and variation rows should compare without being duplicated. If it says `changed`, do NOT accept; inspect the conflict.

## Import safety rules
- New uploads support original `.xlsx` files. CSV is NOT currently supported by the new Supabase workflow (older local uploader still has its own CSV flow).
- Preview is mandatory and saved for up to 45 minutes; subsequent accept is protected by staff session + CSRF token.
- Server-side Supabase service-role credentials are **never exposed to the browser**.
- The importer does not overwrite or delete existing Supabase sales, snapshots, or prices. Conflicting revised exports are blocked for manual review.
- Duplicate reports are skipped. A resumed/partially completed import can append missing batches, but **imports are not atomic**; check server logs on errors and do not delete rows manually.
- Shopee performance reports save both parent and variation rows, but parent and variation revenue must **never** be added together; the cleaned reporting view handles this.
- SG prices are not automatically imported; upload only when the team approves its export.
- Inventory upload requires all Avixo product IDs to already exist in `products`, and monthly movement requires exact existing product names. Unknown products are blocked instead of being guessed. Inventory dates should be month-end or the first day of next month.
- Clinic revenue is an estimate from available Clinic list prices, not realized transaction revenue. Month-to-date movement exports are not treated as exact arbitrary date-range data.
- Historical links matched using the latest October snapshot are provisional; new data doesn't prove historic listing ownership.
- The existing frontend Inventory/Analytics/Product pages still have legacy JSON dependencies. This upgrade connects **Data Management** to Supabase; it does not switch those pages yet.
- The upload page needs the three `v_shopee_sales_clean`, `v_channel_monthly_summary`, and `v_inventory_latest_summary` views already created in your Supabase project.

## Rollback
Stop the upgraded Flask process. Start your untouched original project folder and `app.py`; your Supabase source data was not changed by installing these files.
