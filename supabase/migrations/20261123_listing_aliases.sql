-- Saved pairings between a platform listing and an Avixo product, so a listing that was paired once
-- is matched automatically in every later Stock After Sales upload.
-- Key = the same (market, item id, variation id) used by the Avixo remark links. Variation '0' = whole listing.
create table if not exists public.inv_listing_aliases (
  market text not null,
  item text not null,
  variation text not null default '0',
  avixo_id text not null,
  avixo_name text,
  platform_name text,
  created_by text,
  created_at timestamptz not null default now(),
  primary key (market, item, variation)
);
alter table public.inv_listing_aliases enable row level security;  -- the backend uses the service role; no browser access
