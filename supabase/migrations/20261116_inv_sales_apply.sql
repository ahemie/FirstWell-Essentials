-- Stock After Sales: apply uploaded platform sales to the inventory app as Stock out movements.
-- Called only by the Flask server (service role). One movement group (client_id) per product + channel,
-- so each line can be undone from the Recent tab. Each sales file can be applied only once (sha256).
create table if not exists public.inv_sales_applications (
  id uuid primary key default gen_random_uuid(),
  applied_at timestamptz not null default now(),
  applied_by text not null,
  products integer not null default 0,
  units_applied numeric not null default 0,
  units_short numeric not null default 0,
  shortfalls jsonb not null default '[]'::jsonb
);
create table if not exists public.inv_sales_applied_files (
  sha256 text primary key,
  file_name text not null,
  kind text,
  application_id uuid not null references public.inv_sales_applications(id) on delete cascade,
  applied_at timestamptz not null default now()
);
alter table public.inv_sales_applications enable row level security;
alter table public.inv_sales_applied_files enable row level security;

create or replace function public.inv_apply_sales(p_staff text, p_files jsonb, p_lines jsonb)
returns jsonb
language plpgsql
security definer
set search_path to 'public'
as $$
declare
  app uuid := gen_random_uuid(); f jsonb; l jsonb; pid uuid; qty numeric; avail numeric; take numeric; remaining numeric;
  cid uuid; r record; reason text; n_prod int := 0; u_applied numeric := 0; u_short numeric := 0; short jsonb := '[]'::jsonb;
  dup text;
begin
  if coalesce(trim(p_staff), '') = '' then raise exception 'Missing staff email'; end if;
  if jsonb_typeof(p_files) <> 'array' or jsonb_typeof(p_lines) <> 'array' then raise exception 'Bad input'; end if;
  for f in select * from jsonb_array_elements(p_files) loop
    select file_name into dup from public.inv_sales_applied_files where sha256 = f->>'sha256';
    if dup is not null then raise exception 'ALREADY_APPLIED|%', dup; end if;
  end loop;
  insert into public.inv_sales_applications (id, applied_by) values (app, lower(trim(p_staff)));
  for f in select * from jsonb_array_elements(p_files) loop
    insert into public.inv_sales_applied_files (sha256, file_name, kind, application_id)
    values (f->>'sha256', coalesce(f->>'name', ''), f->>'kind', app);
  end loop;
  for l in select * from jsonb_array_elements(p_lines) loop
    qty := (l->>'qty')::numeric;
    if qty is null or qty <= 0 then continue; end if;
    select id into pid from public.products where avixo_id::text = (l->>'avixo_id');
    if pid is null then
      short := short || jsonb_build_array(jsonb_build_object('avixo_id', l->>'avixo_id', 'channel', l->>'channel', 'qty', qty, 'why', 'product not found'));
      u_short := u_short + qty; continue;
    end if;
    perform pg_advisory_xact_lock(hashtextextended(pid::text, 0));
    select coalesce(sum(b.qty), 0) into avail from public.inv_batches_now(pid) b where b.qty > 0;
    take := least(qty, avail);
    if take < qty then
      short := short || jsonb_build_array(jsonb_build_object('avixo_id', l->>'avixo_id', 'channel', l->>'channel', 'qty', qty - take, 'why', 'not enough stock in the app'));
      u_short := u_short + (qty - take);
    end if;
    if take <= 0 then continue; end if;
    cid := gen_random_uuid(); remaining := take; reason := 'Sold - ' || (l->>'channel');
    for r in select b.expiry_date, b.qty from public.inv_batches_now(pid) b where b.qty > 0
             order by coalesce(b.expiry_date < current_date, false), b.expiry_date nulls last loop
      exit when remaining <= 0;
      insert into public.inv_movements (client_id, product_id, expiry_date, kind, qty_change, reason, note, qty_before, staff_email)
      values (cid, pid, r.expiry_date, 'out', -least(r.qty, remaining), reason, 'Stock After Sales upload', r.qty, lower(trim(p_staff)));
      remaining := remaining - least(r.qty, remaining);
    end loop;
    n_prod := n_prod + 1; u_applied := u_applied + take;
  end loop;
  update public.inv_sales_applications set products = n_prod, units_applied = u_applied, units_short = u_short, shortfalls = short where id = app;
  return jsonb_build_object('ok', true, 'application_id', app, 'products', n_prod, 'units_applied', u_applied, 'units_short', u_short, 'shortfalls', short);
end $$;

revoke all on function public.inv_apply_sales(text, jsonb, jsonb) from public, anon, authenticated;
grant execute on function public.inv_apply_sales(text, jsonb, jsonb) to service_role;
