-- DART on Supabase: the schema serve.py/crm.py kept in SQLite, as Postgres
-- with row-level security. Paste into the Supabase SQL editor and run once.
--
-- Sign-in is Supabase Auth (email + password). Every auth user gets a row in
-- profiles; the first one ever created becomes the approved manager, the rest
-- wait until a manager approves them from the Team screen (which is also how
-- a manager "creates" a user: sign them up, then approve with role + team).

-- ------------------------------------------------------------------ profiles

create table if not exists profiles (
  id          bigint generated always as identity primary key,
  auth_id     uuid unique references auth.users(id) on delete cascade,
  email       text not null,
  name        text not null default '',
  role        text not null default 'mac',      -- manager | mac | expert
  team        text not null default 'Sales',
  approved    boolean not null default false,
  disabled    boolean not null default false,
  created_at  timestamptz not null default now()
);

create or replace function handle_new_auth_user() returns trigger
language plpgsql security definer set search_path = public as $$
declare first_user boolean;
begin
  select not exists (select 1 from profiles) into first_user;
  insert into profiles (auth_id, email, name, role, team, approved)
  values (
    new.id,
    coalesce(new.email, ''),
    coalesce(new.raw_user_meta_data ->> 'name', split_part(coalesce(new.email, ''), '@', 1)),
    case when first_user then 'manager' else 'mac' end,
    case when first_user then 'Management' else 'Sales' end,
    first_user
  );
  return new;
end $$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users for each row execute function handle_new_auth_user();

-- Helpers used by the policies. SECURITY DEFINER so they can read profiles
-- without recursing through profiles' own policies.
create or replace function me_id() returns bigint
language sql stable security definer set search_path = public as $$
  select id from profiles where auth_id = auth.uid()
$$;

create or replace function is_active() returns boolean
language sql stable security definer set search_path = public as $$
  select coalesce((select approved and not disabled from profiles where auth_id = auth.uid()), false)
$$;

create or replace function is_manager() returns boolean
language sql stable security definer set search_path = public as $$
  select coalesce((select approved and not disabled and role = 'manager'
                   from profiles where auth_id = auth.uid()), false)
$$;

-- True until the first account exists: the manager portal shows a
-- "create the first manager" form instead of sign-in.
create or replace function setup_needed() returns boolean
language sql stable security definer set search_path = public as $$
  select not exists (select 1 from profiles)
$$;

-- ------------------------------------------------------------------ CRM

create table if not exists accounts (
  id          bigint generated always as identity primary key,
  name        text not null,
  phone       text not null default '',
  email       text not null default '',
  website     text not null default '',
  industry    text not null default '',
  street      text not null default '',
  city        text not null default '',
  province    text not null default '',
  postcode    text not null default '',
  status      text not null default 'lead',
  owner_id    bigint references profiles(id),
  note        text not null default '',
  created_at  timestamptz not null default now(),
  modified_at timestamptz not null default now()
);

create table if not exists campaigns (
  id            bigint generated always as identity primary key,
  user_id       bigint not null references profiles(id) on delete cascade,
  title         text not null default '',
  note          text not null default '',
  account_name  text not null default '',
  account_phone text not null default '',
  campaign_date text not null default '',
  areas         jsonb not null default '[]'::jsonb,
  businesses    integer not null default 0,
  farms         integer not null default 0,
  status        text not null default 'draft',
  account_id    bigint references accounts(id) on delete set null,
  stage         text not null default 'draft',
  assigned_to   bigint references profiles(id) on delete set null,
  created_at    timestamptz not null default now(),
  modified_at   timestamptz not null default now()
);
create index if not exists idx_campaign_user on campaigns(user_id);
create index if not exists idx_campaign_account on campaigns(account_id);

create table if not exists contacts (
  id          bigint generated always as identity primary key,
  account_id  bigint not null references accounts(id) on delete cascade,
  name        text not null,
  role        text not null default '',
  email       text not null default '',
  phone       text not null default '',
  is_primary  boolean not null default false,
  created_at  timestamptz not null default now()
);
create index if not exists idx_contacts_account on contacts(account_id);

create table if not exists activities (
  id          bigint generated always as identity primary key,
  account_id  bigint references accounts(id) on delete cascade,
  campaign_id bigint references campaigns(id) on delete cascade,
  user_id     bigint not null references profiles(id),
  kind        text not null default 'note',
  subject     text not null default '',
  body        text not null default '',
  due_at      text not null default '',
  done        boolean not null default false,
  created_at  timestamptz not null default now()
);
create index if not exists idx_activity_account on activities(account_id);
create index if not exists idx_activity_campaign on activities(campaign_id);

create table if not exists designs (
  id          bigint generated always as identity primary key,
  campaign_id bigint not null references campaigns(id) on delete cascade,
  name        text not null default '',
  version     integer not null default 1,
  status      text not null default 'draft',
  url         text not null default '',
  note        text not null default '',
  user_id     bigint not null references profiles(id),
  created_at  timestamptz not null default now()
);
create index if not exists idx_designs_campaign on designs(campaign_id);

create table if not exists messages (
  id          bigint generated always as identity primary key,
  campaign_id bigint references campaigns(id) on delete cascade,
  account_id  bigint references accounts(id) on delete cascade,
  user_id     bigint not null references profiles(id),
  to_team     text not null default '',
  body        text not null,
  created_at  timestamptz not null default now()
);
create index if not exists idx_messages_campaign on messages(campaign_id);

-- ------------------------------------------------------------------ RLS

alter table profiles   enable row level security;
alter table accounts   enable row level security;
alter table campaigns  enable row level security;
alter table contacts   enable row level security;
alter table activities enable row level security;
alter table designs    enable row level security;
alter table messages   enable row level security;

-- profiles: everyone active sees the team; you always see yourself (so a
-- pending account can be told it's pending); only managers change roles.
drop policy if exists profiles_select on profiles;
create policy profiles_select on profiles for select
  using (is_active() or auth_id = auth.uid());
drop policy if exists profiles_update on profiles;
create policy profiles_update on profiles for update
  using (is_manager()) with check (is_manager());

-- campaigns: managers see all; others their own or assigned.
drop policy if exists campaigns_select on campaigns;
create policy campaigns_select on campaigns for select
  using (is_manager() or (is_active() and (user_id = me_id() or assigned_to = me_id())));
drop policy if exists campaigns_insert on campaigns;
create policy campaigns_insert on campaigns for insert
  with check (is_active() and user_id = me_id());
drop policy if exists campaigns_update on campaigns;
create policy campaigns_update on campaigns for update
  using (is_manager() or (is_active() and (user_id = me_id() or assigned_to = me_id())));
drop policy if exists campaigns_delete on campaigns;
create policy campaigns_delete on campaigns for delete
  using (is_manager() or (is_active() and (user_id = me_id() or assigned_to = me_id())));

-- Shared CRM tables: any active team member reads and writes.
-- Deleting a client is manager-only, matching serve.py.
drop policy if exists accounts_select on accounts;
drop policy if exists accounts_insert on accounts;
drop policy if exists accounts_update on accounts;
drop policy if exists accounts_delete on accounts;
create policy accounts_select on accounts for select using (is_active());
create policy accounts_insert on accounts for insert with check (is_active());
create policy accounts_update on accounts for update using (is_active()) with check (is_active());
create policy accounts_delete on accounts for delete using (is_manager());

drop policy if exists contacts_all on contacts;
create policy contacts_all on contacts for all using (is_active()) with check (is_active());
drop policy if exists activities_all on activities;
create policy activities_all on activities for all using (is_active()) with check (is_active());
drop policy if exists designs_all on designs;
create policy designs_all on designs for all using (is_active()) with check (is_active());
drop policy if exists messages_all on messages;
create policy messages_all on messages for all using (is_active()) with check (is_active());

grant usage on schema public to anon, authenticated;
grant select, insert, update, delete on all tables in schema public to authenticated;
grant execute on function setup_needed() to anon, authenticated;
grant execute on function me_id(), is_active(), is_manager() to authenticated;
