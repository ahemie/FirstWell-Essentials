-- FirstWell: a saved pairing can point to FirstWell's own Avixo or to FirstStep's Avixo (same product, different IDs).
alter table public.inv_listing_aliases add column if not exists avixo_source text not null default 'firstwell'
  check (avixo_source in ('firstwell', 'firststep'));
