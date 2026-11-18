-- Additive only: two new tables for weekly sales uploads. No existing table is touched.
-- Weekly sales are kept separate from the monthly pipeline so they can never conflict with it.
-- Each import has an explicit period (period_start..period_end). The API refuses overlapping
-- periods for the same channel, so a day can only be counted once.
create table if not exists public.weekly_sales_imports (
  id                uuid primary key default gen_random_uuid(),
  channel           text not null check (channel in ('clinic', 'shopee_my', 'shopee_sg')),
  period_start      date not null,
  period_end        date not null,
  original_filename text not null,
  sha256            text not null unique,
  row_count         integer not null check (row_count >= 0),
  imported_at       timestamptz not null default now(),
  imported_by       text,
  check (period_end >= period_start),
  check (period_end - period_start <= 31),
  unique (channel, period_start, period_end)
);

create table if not exists public.weekly_sales_rows (
  id            bigint generated always as identity primary key,
  import_id     uuid not null references public.weekly_sales_imports(id) on delete cascade,
  channel       text not null check (channel in ('clinic', 'shopee_my', 'shopee_sg')),
  item_key      text not null,            -- Shopee item id, or clinic product name
  name          text,
  product_id    uuid references public.products(id),
  units_sold    numeric not null,
  sales_amount  numeric,                  -- null for clinic (units only, no inventory prices used)
  currency      text check (currency in ('MYR', 'SGD')),
  unique (import_id, item_key)
);
create index if not exists weekly_sales_rows_import_idx on public.weekly_sales_rows(import_id);

alter table public.weekly_sales_imports enable row level security;
alter table public.weekly_sales_rows    enable row level security;
-- No public policies: only the Flask server (service role) reads or writes.
