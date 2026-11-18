-- Additive only: one new table. Does not touch any existing table.
-- Stores each month's processed dashboard JSON (output of process_month.py) exactly as-is,
-- so the Inventory / Analytics / Product pages can show the same numbers as the original files.
create table if not exists public.dashboard_months (
  month_key      text primary key check (month_key ~ '^[0-9]{4}-[0-9]{2}$'),
  label          text not null,
  meta           jsonb not null,
  products       jsonb not null check (jsonb_typeof(products) = 'array'),
  product_count  integer not null check (product_count >= 0),
  source_sha256  text not null,
  source_name    text,
  uploaded_at    timestamptz not null default now(),
  uploaded_by    text
);

-- Same protection as the other tables: RLS on, no public policies.
-- Only the Flask server (service role key) reads or writes it.
alter table public.dashboard_months enable row level security;
