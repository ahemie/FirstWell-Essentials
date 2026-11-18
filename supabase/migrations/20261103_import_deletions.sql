-- Audit trail: who deleted which uploaded report, and when.
-- Written by the Flask server (service role) only. RLS on with no policies = no direct browser access.
create table if not exists public.import_deletions (
  id                uuid primary key default gen_random_uuid(),
  import_id         uuid not null,
  kind              text not null,
  reporting_month   date,
  snapshot_date     date,
  original_filename text,
  source_row_count  integer,
  rows_removed      jsonb,
  deleted_by_email  text not null,
  deleted_by_user_id text,
  deleted_at        timestamptz not null default now()
);
create index if not exists import_deletions_deleted_at_idx on public.import_deletions (deleted_at desc);
alter table public.import_deletions enable row level security;
