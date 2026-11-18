create table if not exists public.channel_fee_rates (
  id bigint generated always as identity primary key,
  marketplace text not null check (marketplace in ('MY','SG')),
  effective_from date not null,
  keep_pct numeric not null check (keep_pct > 0 and keep_pct <= 100),
  voucher_per_unit numeric not null default 0 check (voucher_per_unit >= 0),
  note text,
  created_at timestamptz not null default now(),
  unique (marketplace, effective_from)
);
comment on table public.channel_fee_rates is 'Shopee payout per marketplace. keep_pct = % of the sales price the seller keeps after Shopee fees (80 = 20% fee). voucher_per_unit = voucher cost per unit in that marketplace currency (MYR for MY, SGD for SG). A rate applies from effective_from (use the 1st of a month) until the next row.';
alter table public.channel_fee_rates enable row level security;
insert into public.channel_fee_rates (marketplace, effective_from, keep_pct, voucher_per_unit, note) values
  ('MY', '2026-01-01', 80, 0, 'Starting rate: Shopee takes 20%'),
  ('SG', '2026-01-01', 70, 0, 'Starting rate: Shopee takes 30%')
on conflict (marketplace, effective_from) do nothing;
