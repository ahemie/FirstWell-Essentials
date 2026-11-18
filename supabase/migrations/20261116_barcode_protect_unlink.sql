-- Barcode safety: refuse to silently move a barcode that is already linked to another product,
-- and add an unlink function for the Barcodes tab.
drop function if exists public.inv_barcode_link(text, uuid);

create or replace function public.inv_barcode_link(p_barcode text, p_product uuid, p_force boolean default false)
returns jsonb
language plpgsql
security definer
set search_path to 'public'
as $$
declare e text := public.inv_require_staff(); b text := trim(coalesce(p_barcode, '')); cur uuid; cur_name text;
begin
  if length(b) < 3 or length(b) > 64 then raise exception 'Barcode looks wrong'; end if;
  if not exists (select 1 from public.products where id = p_product) then raise exception 'Unknown product'; end if;
  select product_id into cur from public.inv_barcodes where barcode = b;
  if cur is not null and cur <> p_product and not coalesce(p_force, false) then
    select name into cur_name from public.products where id = cur;
    raise exception 'ALREADY_LINKED|%', coalesce(cur_name, 'another product');
  end if;
  insert into public.inv_barcodes (barcode, product_id, created_by) values (b, p_product, e)
  on conflict (barcode) do update set product_id = excluded.product_id, created_by = excluded.created_by;
  return jsonb_build_object('ok', true);
end $$;

create or replace function public.inv_barcode_unlink(p_barcode text)
returns jsonb
language plpgsql
security definer
set search_path to 'public'
as $$
declare e text := public.inv_require_staff();
begin
  delete from public.inv_barcodes where barcode = trim(coalesce(p_barcode, ''));
  return jsonb_build_object('ok', true);
end $$;

revoke all on function public.inv_barcode_link(text, uuid, boolean) from public, anon;
revoke all on function public.inv_barcode_unlink(text) from public, anon;
grant execute on function public.inv_barcode_link(text, uuid, boolean) to authenticated, service_role;
grant execute on function public.inv_barcode_unlink(text) to authenticated, service_role;
