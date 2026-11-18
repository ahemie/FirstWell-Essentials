-- Stock After Sales history: remember what each confirmed upload did, line by line, so it can be checked later.
alter table public.inv_sales_applications add column if not exists inventory_file text;
alter table public.inv_sales_applications add column if not exists inventory_date text;

create table if not exists public.inv_sales_application_lines (
  id bigint generated always as identity primary key,
  application_id uuid not null references public.inv_sales_applications(id) on delete cascade,
  avixo_id text,
  product_id uuid,
  product_name text,
  channel text not null,
  qty_sold numeric not null,
  qty_applied numeric not null default 0,
  qty_short numeric not null default 0,
  avixo_before numeric,
  avixo_after numeric,
  app_before numeric,
  app_after numeric,
  client_id uuid,
  why text
);
create index if not exists inv_sales_lines_app_idx on public.inv_sales_application_lines(application_id);
alter table public.inv_sales_application_lines enable row level security;

drop function if exists public.inv_apply_sales(text, jsonb, jsonb);
create or replace function public.inv_apply_sales(p_staff text, p_files jsonb, p_lines jsonb, p_inventory jsonb default '{}'::jsonb)
returns jsonb
language plpgsql
security definer
set search_path to 'public'
as $$
declare
  app uuid := gen_random_uuid(); f jsonb; l jsonb; pid uuid; qty numeric; avail numeric; take numeric; remaining numeric;
  cid uuid; r record; reason text; n_prod int := 0; u_applied numeric := 0; u_short numeric := 0; short jsonb := '[]'::jsonb;
  dup text; pname text; why text;
begin
  if coalesce(trim(p_staff), '') = '' then raise exception 'Missing staff email'; end if;
  if jsonb_typeof(p_files) <> 'array' or jsonb_typeof(p_lines) <> 'array' then raise exception 'Bad input'; end if;
  for f in select * from jsonb_array_elements(p_files) loop
    select file_name into dup from public.inv_sales_applied_files where sha256 = f->>'sha256';
    if dup is not null then raise exception 'ALREADY_APPLIED|%', dup; end if;
  end loop;
  insert into public.inv_sales_applications (id, applied_by, inventory_file, inventory_date)
  values (app, lower(trim(p_staff)), p_inventory->>'file', p_inventory->>'when');
  for f in select * from jsonb_array_elements(p_files) loop
    insert into public.inv_sales_applied_files (sha256, file_name, kind, application_id)
    values (f->>'sha256', coalesce(f->>'name', ''), f->>'kind', app);
  end loop;
  for l in select * from jsonb_array_elements(p_lines) loop
    qty := (l->>'qty')::numeric;
    if qty is null or qty <= 0 then continue; end if;
    cid := null; why := null; take := 0; avail := null;
    select id, name into pid, pname from public.products where avixo_id::text = (l->>'avixo_id');
    pname := coalesce(pname, l->>'name');
    if pid is null then
      why := 'product not found';
      short := short || jsonb_build_array(jsonb_build_object('avixo_id', l->>'avixo_id', 'channel', l->>'channel', 'qty', qty, 'why', why));
      u_short := u_short + qty;
    else
      perform pg_advisory_xact_lock(hashtextextended(pid::text, 0));
      select coalesce(sum(b.qty), 0) into avail from public.inv_batches_now(pid) b where b.qty > 0;
      take := least(qty, avail);
      if take < qty then
        why := 'not enough stock in the app';
        short := short || jsonb_build_array(jsonb_build_object('avixo_id', l->>'avixo_id', 'channel', l->>'channel', 'qty', qty - take, 'why', why));
        u_short := u_short + (qty - take);
      end if;
      if take > 0 then
        cid := gen_random_uuid(); remaining := take; reason := 'Sold - ' || (l->>'channel');
        for r in select b.expiry_date, b.qty from public.inv_batches_now(pid) b where b.qty > 0
                 order by coalesce(b.expiry_date < current_date, false), b.expiry_date nulls last loop
          exit when remaining <= 0;
          insert into public.inv_movements (client_id, product_id, expiry_date, kind, qty_change, reason, note, qty_before, staff_email)
          values (cid, pid, r.expiry_date, 'out', -least(r.qty, remaining), reason, 'Stock After Sales upload', r.qty, lower(trim(p_staff)));
          remaining := remaining - least(r.qty, remaining);
        end loop;
        n_prod := n_prod + 1; u_applied := u_applied + take;
      end if;
    end if;
    insert into public.inv_sales_application_lines
      (application_id, avixo_id, product_id, product_name, channel, qty_sold, qty_applied, qty_short, avixo_before, avixo_after, app_before, app_after, client_id, why)
    values (app, l->>'avixo_id', pid, pname, l->>'channel', qty, take, qty - take, nullif(l->>'avixo_before', '')::numeric,
            nullif(l->>'avixo_after', '')::numeric, avail, case when avail is null then null else avail - take end, cid, why);
  end loop;
  update public.inv_sales_applications set products = n_prod, units_applied = u_applied, units_short = u_short, shortfalls = short where id = app;
  return jsonb_build_object('ok', true, 'application_id', app, 'products', n_prod, 'units_applied', u_applied, 'units_short', u_short, 'shortfalls', short);
end $$;

-- History: with no id, the list of confirmed uploads; with an id, its lines (and whether each was undone later).
create or replace function public.inv_sales_history(p_id uuid default null)
returns jsonb
language plpgsql
stable
security definer
set search_path to 'public'
as $$
begin
  if p_id is null then
    return coalesce((select jsonb_agg(x order by x->>'applied_at' desc) from (
      select jsonb_build_object('id', a.id, 'applied_at', a.applied_at, 'applied_by', a.applied_by, 'products', a.products,
        'units_applied', a.units_applied, 'units_short', a.units_short, 'inventory_file', a.inventory_file, 'inventory_date', a.inventory_date,
        'files', coalesce((select jsonb_agg(jsonb_build_object('name', f.file_name, 'slot', f.kind) order by f.file_name)
                           from public.inv_sales_applied_files f where f.application_id = a.id), '[]'::jsonb)) as x
      from public.inv_sales_applications a order by a.applied_at desc limit 100) t), '[]'::jsonb);
  end if;
  return coalesce((select jsonb_agg(jsonb_build_object('product', l.product_name, 'avixo_id', l.avixo_id, 'channel', l.channel,
      'sold', l.qty_sold, 'applied', l.qty_applied, 'short', l.qty_short, 'avixo_before', l.avixo_before, 'avixo_after', l.avixo_after,
      'app_before', l.app_before, 'app_after', l.app_after, 'why', l.why,
      'undone', l.client_id is not null and not exists (
          select 1 from public.inv_movements m where m.client_id = l.client_id and m.kind = 'out' and m.qty_change <> 0
            and not exists (select 1 from public.inv_movements u where u.reverses_id = m.id))
    ) order by l.product_name, l.channel) from public.inv_sales_application_lines l where l.application_id = p_id), '[]'::jsonb);
end $$;

revoke all on function public.inv_apply_sales(text, jsonb, jsonb, jsonb) from public, anon, authenticated;
revoke all on function public.inv_sales_history(uuid) from public, anon, authenticated;
grant execute on function public.inv_apply_sales(text, jsonb, jsonb, jsonb) to service_role;
grant execute on function public.inv_sales_history(uuid) to service_role;
