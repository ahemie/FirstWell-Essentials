create table if not exists public.supabase_upload_previews (
  token text primary key,
  staff_id text not null,
  kind text not null,
  month text not null,
  snapshot text,
  name text not null,
  fingerprint text not null,
  prepared_json jsonb not null,
  created_at timestamptz not null default now()
);
create index if not exists supabase_upload_previews_created_at_idx on public.supabase_upload_previews (created_at);
-- Server-side staging only (service role). RLS on with no policies = no access for anon/authenticated roles.
alter table public.supabase_upload_previews enable row level security;
