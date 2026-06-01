-- Email-signup support for public.users
-- ------------------------------------------------------------------
-- Fixes "Database error saving new user" on email sign-up.
--
-- The table was built phone-first: `phone` was NOT NULL with an E.164 CHECK,
-- and the new-user trigger inserted COALESCE(NEW.phone, '') — which for an
-- email signup is '', violating the E.164 check and aborting the signup.
--
-- This makes phone optional and teaches the trigger to handle BOTH phone and
-- email signups. Safe to run anytime (idempotent). Run in the Supabase SQL editor.

-- 1. Phone becomes optional (email users have no phone).
alter table public.users alter column phone drop not null;

-- 2. Allow NULL phone; keep E.164 format check for real numbers.
alter table public.users drop constraint if exists users_phone_e164;
alter table public.users add constraint users_phone_e164
    check (phone is null or phone ~ '^\+[1-9]\d{6,14}$');

-- 3. Trigger now provisions BOTH phone- and email-created auth users.
create or replace function public.handle_new_auth_user()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
    insert into public.users (auth_id, phone, phone_verified_at, email)
    values (
        new.id,
        nullif(new.phone, ''),                       -- NULL for email signups
        case
            when new.phone_confirmed_at is not null then new.phone_confirmed_at
            when nullif(new.phone, '') is not null   then now()
            else null
        end,
        new.email                                    -- populated for email signups
    )
    on conflict (auth_id) do nothing;
    return new;
end;
$$;
