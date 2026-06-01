-- Per-user personalization fix
-- ------------------------------------------------------------------
-- Adds user scoping to the interactions table so each user's cook
-- history drives ONLY their own recommendations (previously all
-- interactions were blended into one global preference profile).
--
-- Safe to run anytime: column is nullable, so existing rows and
-- anonymous (logged-out) interactions keep working. Run in the
-- Supabase SQL editor.

alter table public.interactions
  add column if not exists user_id uuid references public.users(id) on delete cascade;

create index if not exists idx_interactions_user_id
  on public.interactions (user_id);

-- Speeds up the per-user "cook history" lookup used to build preferences.
create index if not exists idx_interactions_user_action
  on public.interactions (user_id, action);
