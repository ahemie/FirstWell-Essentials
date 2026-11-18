-- Stock After Sales no longer changes the inventory app's stock. A confirmed calculation is only saved as history.
alter table public.inv_sales_applications add column if not exists mode text not null default 'stock';  -- 'stock' = the earlier version that deducted app stock, 'record' = history only
alter table public.inv_sales_applications add column if not exists sales_date text;
alter table public.inv_sales_application_lines add column if not exists remark text;

-- The function that wrote Stock out entries is removed so nothing can deduct app stock any more.
drop function if exists public.inv_apply_sales(text, jsonb, jsonb, jsonb);

create or replace function public.inv_sales_record(p_staff text, p_files jsonb, p_lines jsonb, p_meta jsonb default '{}'::jsonb)
returns jsonb
language plpgsql
security definer
set search_path to 'public'
as $$
declare
  app uuid := gen_random_uuid(); f jsonb; l jsonb; dup text; n int := 0; u numeric := 0;
begin
  if coalesce(trim(p_staff), '') = '' then raise exception 'Missing staff email'; end if;
  if jsonb_typeof(p_files) <> 'array' or jsonb_typeof(p_lines) <> 'array' then raise exception 'Bad input'; end if;
  for f in select * from jsonb_array_elements(p_files) loop
    select file_name into dup from public.inv_sales_applied_files where sha256 = f->>'sha256';
    if dup is not null then raise exception 'ALREADY_SAVED|%', dup; end if;
  end loop;
  insert into public.inv_sales_applications (id, applied_by, inventory_file, inventory_date, sales_date, mode)
  values (app, lower(trim(p_staff)), p_meta->>'file', p_meta->>'when', p_meta->>'sales_date', 'record');
  for f in select * from jsonb_array_elements(p_files) loop
    insert into public.inv_sales_applied_files (sha256, file_name, kind, application_id)
    values (f->>'sha256', coalesce(f->>'name', ''), f->>'kind', app);
  end loop;
  for l in select * from jsonb_array_elements(p_lines) loop
    insert into public.inv_sales_application_lines (application_id, avixo_id, product_name, channel, qty_sold, qty_applied, qty_short, avixo_before, avixo_after, remark)
    values (app, l->>'avixo_id', l->>'name', l->>'channel', (l->>'qty')::numeric, 0, 0,
            nullif(l->>'avixo_before', '')::numeric, nullif(l->>'avixo_after', '')::numeric, l->>'remark');
    n := n + 1; u := u + (l->>'qty')::numeric;
  end loop;
  update public.inv_sales_applications set products = n, units_applied = u where id = app;
  return jsonb_build_object('ok', true, 'application_id', app, 'lines', n, 'units', u);
end $$;

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
      select jsonb_build_object('id', a.id, 'applied_at', a.applied_at, 'applied_by', a.applied_by, 'products', a.products, 'mode', a.mode,
        'sales_date', a.sales_date, 'units_applied', a.units_applied, 'units_short', a.units_short, 'inventory_file', a.inventory_file, 'inventory_date', a.inventory_date,
        'files', coalesce((select jsonb_agg(jsonb_build_object('name', f.file_name, 'slot', f.kind) order by f.file_name)
                           from public.inv_sales_applied_files f where f.application_id = a.id), '[]'::jsonb)) as x
      from public.inv_sales_applications a order by a.applied_at desc limit 100) t), '[]'::jsonb);
  end if;
  return coalesce((select jsonb_agg(jsonb_build_object('product', l.product_name, 'avixo_id', l.avixo_id, 'channel', l.channel,
      'sold', l.qty_sold, 'applied', l.qty_applied, 'short', l.qty_short, 'avixo_before', l.avixo_before, 'avixo_after', l.avixo_after,
      'app_before', l.app_before, 'app_after', l.app_after, 'why', l.why, 'remark', l.remark,
      'undone', l.client_id is not null and not exists (
          select 1 from public.inv_movements m where m.client_id = l.client_id and m.kind = 'out' and m.qty_change <> 0
            and not exists (select 1 from public.inv_movements u where u.reverses_id = m.id))
    ) order by l.product_name, l.channel) from public.inv_sales_application_lines l where l.application_id = p_id), '[]'::jsonb);
end $$;

revoke all on function public.inv_sales_record(text, jsonb, jsonb, jsonb) from public, anon, authenticated;
grant execute on function public.inv_sales_record(text, jsonb, jsonb, jsonb) to service_role;
