"""
check_limit() — tiered usage gate

Called before any gated feature executes. Reads tier_limits and usage_log
from Supabase Postgres to decide whether the user is within their allowance.

Enforcement is dormant on day one: every tier_limits row ships with
enforcement_enabled = FALSE. Flip it to TRUE for 'free' after ~3 months of
usage data collection.

  UPDATE tier_limits SET enforcement_enabled = TRUE WHERE tier = 'free';

Until that UPDATE runs, check_limit() is a no-op for all users (it logs
usage but never blocks).

Usage in a route:
    check_limit(user, "decide_for_me")   # raises 429 if over limit
    # ... feature code ...
    log_usage(user, "decide_for_me")     # record after success
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import uuid4

from fastapi import HTTPException, status

from .supabase_client import supabase_admin

# Valid feature keys — must match tier_limits columns and usage_log CHECK constraint
Feature = Literal[
    "decide_for_me",
    "ask_chef",
    "pantry_items",
    "collections",
    "meal_plan",
    "goal_tracking",
    "advanced_taste_dna",
]

# How far back to count usage for each feature.
# "daily" = last 24 hours; "weekly" = last 7 days.
_FEATURE_WINDOW: dict[str, timedelta] = {
    "decide_for_me":       timedelta(hours=24),
    "ask_chef":            timedelta(hours=24),
    "pantry_items":        timedelta(hours=24),
    "collections":         timedelta(hours=24),
    "meal_plan":           timedelta(days=7),
    "goal_tracking":       timedelta(hours=24),
    "advanced_taste_dna":  timedelta(hours=24),
}

# Maps feature name → tier_limits column name
_FEATURE_COLUMN: dict[str, str] = {
    "decide_for_me":       "decide_for_me_daily",
    "ask_chef":            "ask_chef_daily",
    "pantry_items":        "pantry_items_daily",
    "collections":         "collections_total",
    "meal_plan":           "meal_plan_weekly",
    "goal_tracking":       "goal_tracking_daily",
    "advanced_taste_dna":  "advanced_taste_dna_daily",
}


def check_limit(user: dict, feature: Feature, session_id: str | None = None) -> None:
    """
    Raise HTTP 429 if the user has hit their tier limit for `feature`.
    Does nothing if enforcement_enabled is FALSE for their tier.

    Call this BEFORE the feature executes.
    Call log_usage() AFTER the feature succeeds.
    """
    tier: str = user.get("tier", "free")
    user_id: str = user["id"]

    # ── 1. Fetch tier limits ──────────────────────────────────────────────────
    limit_row = (
        supabase_admin
        .table("tier_limits")
        .select("*")
        .eq("tier", tier)
        .maybe_single()
        .execute()
    )

    # No config row → allow (fail open, never block in misconfigured state)
    if not limit_row.data:
        return

    row = limit_row.data

    # Enforcement globally disabled for this tier → skip counting, just return
    if not row.get("enforcement_enabled", False):
        return

    # ── 2. Resolve limit value ────────────────────────────────────────────────
    col = _FEATURE_COLUMN.get(feature)
    if col is None:
        return  # Unknown feature — allow

    limit_value: int | None = row.get(col)
    if limit_value is None:
        return  # NULL limit = unlimited for this tier

    # ── 3. Count recent usage ─────────────────────────────────────────────────
    window = _FEATURE_WINDOW.get(feature, timedelta(hours=24))
    cutoff = (datetime.now(timezone.utc) - window).isoformat()

    count_result = (
        supabase_admin
        .table("usage_log")
        .select("id", count="exact")
        .eq("user_id", user_id)
        .eq("feature", feature)
        .gte("used_at", cutoff)
        .execute()
    )

    used_count: int = count_result.count or 0

    # ── 4. Gate ───────────────────────────────────────────────────────────────
    if used_count >= limit_value:
        window_label = "day" if window <= timedelta(hours=24) else "week"
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "code":        "limit_reached",
                "feature":     feature,
                "tier":        tier,
                "limit":       limit_value,
                "used":        used_count,
                "window":      window_label,
                "upgrade_url": "/upgrade",
                "message": (
                    f"You've used {feature.replace('_', ' ')} {used_count} times "
                    f"today. Upgrade to Pro for unlimited access."
                ),
            },
        )


def log_usage(
    user: dict,
    feature: Feature,
    session_id: str | None = None,
    metadata: dict | None = None,
) -> None:
    """
    Record a feature usage event in usage_log.
    Non-blocking: if the insert fails, it is silently swallowed so the
    feature response is never blocked by a logging error.
    """
    try:
        supabase_admin.table("usage_log").insert({
            "id":         str(uuid4()),
            "user_id":    user["id"],
            "feature":    feature,
            "session_id": session_id,
            "metadata":   metadata or {},
        }).execute()
    except Exception as exc:
        # Log error to stdout (Render captures stdout → logs)
        print(f"[usage_log] Insert failed for user={user['id']} feature={feature}: {exc}")
