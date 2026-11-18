-- Shopee listings that are not Avixo products (e.g. free gifts). They are shown as "Free item" with a readable
-- name in the BI "Products with no sales" list instead of "Unmapped listing <id>".
create table if not exists public.listing_flags (
  marketplace text not null check (marketplace in ('MY','SG')),
  shopee_item_id text not null,
  flag text not null default 'free_item' check (flag in ('free_item')),
  display_name text,
  note text,
  created_at timestamptz not null default now(),
  primary key (marketplace, shopee_item_id)
);
comment on table public.listing_flags is 'Marks Shopee listings that have no Avixo product. flag=free_item: free gift/bonus item. display_name is the name shown on the dashboard.';
alter table public.listing_flags enable row level security;
insert into public.listing_flags (marketplace, shopee_item_id, flag, display_name, note) values
  ('MY','41784955182','free_item','Esential Insta Freeze Spray 100ml','free item'),
  ('MY','46719764482','free_item','Raraberry Rice Cereal 100g','free item'),
  ('MY','55768782865','free_item','Mustela Arnica Gel with Organic Calendula 100ml','free item'),
  ('MY','57506998480','free_item','Kabrita Baby Goat''s Milk Infant Formula Step 1 (0–12 Months) 400g','free item'),
  ('MY','15198188269','free_item','Esberitox Chewable Tablet (100s)','free item')
on conflict (marketplace, shopee_item_id) do nothing;
