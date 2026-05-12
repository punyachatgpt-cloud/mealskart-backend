-- ═══════════════════════════════════════════════════════════════
-- SIMMER AUTH SCHEMA  —  v2  (run once, idempotent)
-- Paste this entire file into: Supabase Dashboard → SQL Editor → New query
-- ═══════════════════════════════════════════════════════════════

-- EXTENSIONS
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";


-- ═══════════════════════════════════════════════════════════════
-- ENUM TYPES
-- ═══════════════════════════════════════════════════════════════

DO $$ BEGIN
    CREATE TYPE user_tier  AS ENUM ('free', 'pro');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE otp_status AS ENUM ('sent', 'verified', 'failed', 'expired');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;


-- ═══════════════════════════════════════════════════════════════
-- SHARED TRIGGER: auto-update updated_at
-- ═══════════════════════════════════════════════════════════════

CREATE OR REPLACE FUNCTION public.set_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;


-- ═══════════════════════════════════════════════════════════════
-- TABLE: public.users
-- ═══════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS public.users (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    auth_id             UUID        UNIQUE REFERENCES auth.users(id) ON DELETE CASCADE,
    phone               TEXT        NOT NULL,
    CONSTRAINT users_phone_unique  UNIQUE (phone),
    CONSTRAINT users_phone_e164    CHECK  (phone ~ '^\+[1-9]\d{6,14}$'),
    phone_verified_at   TIMESTAMPTZ,
    email               TEXT,
    CONSTRAINT users_email_unique  UNIQUE (email),
    CONSTRAINT users_email_format  CHECK  (email ~* '^[^@\s]+@[^@\s]+\.[^@\s]+$'),
    display_name        TEXT,
    city                TEXT,
    tier                user_tier   NOT NULL DEFAULT 'free',
    tier_started_at     TIMESTAMPTZ,
    tier_expires_at     TIMESTAMPTZ,
    is_early_access     BOOLEAN     NOT NULL DEFAULT FALSE,
    onboarding_complete BOOLEAN     NOT NULL DEFAULT FALSE,
    is_banned           BOOLEAN     NOT NULL DEFAULT FALSE,
    ban_reason          TEXT,
    deleted_at          TIMESTAMPTZ,
    last_seen_at        TIMESTAMPTZ,
    metadata            JSONB       NOT NULL DEFAULT '{}',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_users_phone     ON public.users (phone);
CREATE INDEX IF NOT EXISTS idx_users_email     ON public.users (email) WHERE email IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_users_auth_id   ON public.users (auth_id);
CREATE INDEX IF NOT EXISTS idx_users_tier      ON public.users (tier);
CREATE INDEX IF NOT EXISTS idx_users_last_seen ON public.users (last_seen_at DESC NULLS LAST);
CREATE INDEX IF NOT EXISTS idx_users_active    ON public.users (id) WHERE deleted_at IS NULL;

DROP TRIGGER IF EXISTS trg_users_updated_at ON public.users;
CREATE TRIGGER trg_users_updated_at
    BEFORE UPDATE ON public.users
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

ALTER TABLE public.users ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "users_select_own" ON public.users;
CREATE POLICY "users_select_own"
    ON public.users FOR SELECT
    USING (auth.uid() = auth_id AND deleted_at IS NULL);

DROP POLICY IF EXISTS "users_update_own" ON public.users;
CREATE POLICY "users_update_own"
    ON public.users FOR UPDATE
    USING (auth.uid() = auth_id AND deleted_at IS NULL);


-- ═══════════════════════════════════════════════════════════════
-- TRIGGER: auto-create public.users on Supabase Auth OTP verify
-- ═══════════════════════════════════════════════════════════════

CREATE OR REPLACE FUNCTION public.handle_new_auth_user()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
    INSERT INTO public.users (auth_id, phone, phone_verified_at)
    VALUES (
        NEW.id,
        COALESCE(NEW.phone, ''),
        CASE WHEN NEW.phone_confirmed_at IS NOT NULL
             THEN NEW.phone_confirmed_at
             ELSE NOW()
        END
    )
    ON CONFLICT (auth_id) DO NOTHING;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_on_new_auth_user ON auth.users;
CREATE TRIGGER trg_on_new_auth_user
    AFTER INSERT ON auth.users
    FOR EACH ROW
    EXECUTE FUNCTION public.handle_new_auth_user();


-- ═══════════════════════════════════════════════════════════════
-- TABLE: public.tier_limits
-- Columns named to match limits.py _FEATURE_COLUMN mapping exactly.
-- enforcement_enabled = FALSE day one; flip for 'free' at month 3.
-- ═══════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS public.tier_limits (
    tier                        user_tier   PRIMARY KEY,

    -- Daily / weekly count caps (NULL = unlimited for Pro)
    decide_for_me_daily         INT,
    ask_chef_daily              INT,
    pantry_items_daily          INT,
    collections_daily           INT,
    meal_plan_weekly            INT,
    goal_tracking_daily         INT,
    advanced_taste_dna_daily    INT,

    -- UX flags
    ads_shown                   BOOLEAN     NOT NULL DEFAULT TRUE,

    -- THE single paywall switch
    -- Day one: FALSE  — checkLimit() always returns allowed:true
    -- Month 3: UPDATE tier_limits SET enforcement_enabled = TRUE WHERE tier = 'free';
    enforcement_enabled         BOOLEAN     NOT NULL DEFAULT FALSE,

    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

DROP TRIGGER IF EXISTS trg_tier_limits_updated_at ON public.tier_limits;
CREATE TRIGGER trg_tier_limits_updated_at
    BEFORE UPDATE ON public.tier_limits
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

ALTER TABLE public.tier_limits ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "tier_limits_readable_by_authenticated" ON public.tier_limits;
CREATE POLICY "tier_limits_readable_by_authenticated"
    ON public.tier_limits FOR SELECT
    TO authenticated
    USING (TRUE);

-- Seed — INSERT or do nothing if already exists
INSERT INTO public.tier_limits (
    tier,
    decide_for_me_daily, ask_chef_daily, pantry_items_daily,
    collections_daily, meal_plan_weekly, goal_tracking_daily,
    advanced_taste_dna_daily, ads_shown, enforcement_enabled
) VALUES
('free', 5,    10,   10,   3,    7,    3,    1,    TRUE,  FALSE),
('pro',  NULL, NULL, NULL, NULL, NULL, NULL, NULL, FALSE, FALSE)
ON CONFLICT (tier) DO NOTHING;


-- ═══════════════════════════════════════════════════════════════
-- TABLE: public.usage_log
-- ═══════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS public.usage_log (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID        NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    feature     TEXT        NOT NULL,
    CONSTRAINT valid_feature CHECK (feature IN (
        'decide_for_me', 'ask_chef', 'pantry_items',
        'collections', 'meal_plan', 'goal_tracking', 'advanced_taste_dna'
    )),
    session_id  TEXT,
    used_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata    JSONB       NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_usage_log_user_feature_time
    ON public.usage_log (user_id, feature, used_at DESC);

-- Note: partial indexes with NOW() are invalid (NOW() is STABLE not IMMUTABLE).
-- idx_usage_log_user_feature_time above already covers the daily-count queries.

ALTER TABLE public.usage_log ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "usage_log_select_own" ON public.usage_log;
CREATE POLICY "usage_log_select_own"
    ON public.usage_log FOR SELECT
    USING (user_id = (
        SELECT id FROM public.users
        WHERE auth_id = auth.uid() AND deleted_at IS NULL
    ));


-- ═══════════════════════════════════════════════════════════════
-- TABLE: public.otp_requests  (rate-limit only — no OTP codes stored)
-- ═══════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS public.otp_requests (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    phone           TEXT        NOT NULL,
    CONSTRAINT otp_phone_e164 CHECK (phone ~ '^\+[1-9]\d{6,14}$'),
    ip_address      TEXT        NOT NULL DEFAULT 'unknown',
    status          otp_status  NOT NULL DEFAULT 'sent',
    requested_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    verified_at     TIMESTAMPTZ,
    expires_at      TIMESTAMPTZ NOT NULL DEFAULT (NOW() + INTERVAL '5 minutes'),
    metadata        JSONB       NOT NULL DEFAULT '{}'
);

-- Full indexes on rate-limit query columns
-- (partial indexes with NOW() are invalid — NOW() is STABLE not IMMUTABLE)
CREATE INDEX IF NOT EXISTS idx_otp_phone_time
    ON public.otp_requests (phone, requested_at DESC);

CREATE INDEX IF NOT EXISTS idx_otp_ip_time
    ON public.otp_requests (ip_address, requested_at DESC);


-- ═══════════════════════════════════════════════════════════════
-- TABLE: public.subscriptions  (placeholder — payment not wired yet)
-- ═══════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS public.subscriptions (
    id                          UUID    PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id                     UUID    NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    provider                    TEXT,
    CONSTRAINT valid_provider CHECK (provider IN ('razorpay', 'stripe', 'manual', NULL)),
    provider_subscription_id    TEXT,
    provider_plan_id            TEXT,
    status                      TEXT    NOT NULL DEFAULT 'pending',
    CONSTRAINT valid_subscription_status CHECK (status IN (
        'pending', 'active', 'trialing', 'past_due', 'canceled', 'expired'
    )),
    started_at                  TIMESTAMPTZ,
    expires_at                  TIMESTAMPTZ,
    canceled_at                 TIMESTAMPTZ,
    next_billing_at             TIMESTAMPTZ,
    amount_units                INT,
    currency                    TEXT    NOT NULL DEFAULT 'INR',
    metadata                    JSONB   NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_subscriptions_user    ON public.subscriptions (user_id);
CREATE INDEX IF NOT EXISTS idx_subscriptions_status  ON public.subscriptions (status);
CREATE INDEX IF NOT EXISTS idx_subscriptions_expires ON public.subscriptions (expires_at)
    WHERE status = 'active';

DROP TRIGGER IF EXISTS trg_subscriptions_updated_at ON public.subscriptions;
CREATE TRIGGER trg_subscriptions_updated_at
    BEFORE UPDATE ON public.subscriptions
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

ALTER TABLE public.subscriptions ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "subscriptions_select_own" ON public.subscriptions;
CREATE POLICY "subscriptions_select_own"
    ON public.subscriptions FOR SELECT
    USING (user_id = (
        SELECT id FROM public.users
        WHERE auth_id = auth.uid() AND deleted_at IS NULL
    ));


-- ═══════════════════════════════════════════════════════════════
-- TABLE: public.recovery_requests
-- ═══════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS public.recovery_requests (
    id              UUID    PRIMARY KEY DEFAULT gen_random_uuid(),
    old_phone       TEXT    NOT NULL,
    new_phone       TEXT    NOT NULL,
    CONSTRAINT recovery_old_phone_e164 CHECK (old_phone ~ '^\+[1-9]\d{6,14}$'),
    CONSTRAINT recovery_new_phone_e164 CHECK (new_phone ~ '^\+[1-9]\d{6,14}$'),
    CONSTRAINT recovery_phones_differ  CHECK (old_phone <> new_phone),
    contact_email   TEXT,
    reason          TEXT,
    status          TEXT    NOT NULL DEFAULT 'pending',
    CONSTRAINT valid_recovery_status CHECK (status IN (
        'pending', 'approved', 'rejected', 'needs_info'
    )),
    ip_address      TEXT,
    reviewed_by     TEXT,
    reviewed_at     TIMESTAMPTZ,
    admin_note      TEXT,
    requested_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_recovery_old_phone ON public.recovery_requests (old_phone);
CREATE INDEX IF NOT EXISTS idx_recovery_status    ON public.recovery_requests (status)
    WHERE status = 'pending';


-- ═══════════════════════════════════════════════════════════════
-- VERIFY (run after migration to confirm all tables exist)
-- ═══════════════════════════════════════════════════════════════
SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'public'
  AND table_name IN (
    'users','tier_limits','usage_log',
    'otp_requests','subscriptions','recovery_requests'
  )
ORDER BY table_name;
