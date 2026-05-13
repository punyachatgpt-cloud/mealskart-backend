"""
Auth routes — all mounted at /auth/* by fastapi_app.py.

Endpoints:
  POST /auth/request-otp    — rate-limit check + send OTP via Supabase Auth
  POST /auth/verify-otp     — verify OTP + return JWT
  GET  /auth/me             — return current user profile
  POST /auth/onboarding     — save display_name + diet/cuisines preferences
  POST /auth/logout         — revoke Supabase session
  POST /auth/check-limit    — check + log usage for a gated feature (Phase 5)

Rules:
  - No existing routes are modified.
  - No SQLite / recipe logic is touched.
  - All user data goes to Supabase Postgres.
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, field_validator

from .dependencies import get_current_user, get_optional_user
from .limits import Feature, check_limit, log_usage
from .supabase_client import supabase_admin

load_dotenv()

router = APIRouter(prefix="/auth", tags=["auth"])

# ── Constants ──────────────────────────────────────────────────────────────────
_E164_RE = re.compile(r"^\+[1-9]\d{6,14}$")

# Rate-limit windows (enforced in otp_requests table)
_OTP_PHONE_LIMIT   = 3    # sends per phone per window
_OTP_PHONE_WINDOW  = timedelta(minutes=15)
_OTP_IP_LIMIT      = 10   # sends per IP per window
_OTP_IP_WINDOW     = timedelta(hours=1)


# ── Pydantic models ────────────────────────────────────────────────────────────

class OtpRequest(BaseModel):
    phone: str

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        v = v.strip()
        if not _E164_RE.match(v):
            raise ValueError(
                "Phone must be in E.164 format, e.g. +919876543210"
            )
        return v


class OtpVerifyRequest(BaseModel):
    phone: str
    otp: str

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        v = v.strip()
        if not _E164_RE.match(v):
            raise ValueError("Phone must be in E.164 format, e.g. +919876543210")
        return v

    @field_validator("otp")
    @classmethod
    def validate_otp(cls, v: str) -> str:
        v = v.strip()
        if not re.fullmatch(r"\d{4,8}", v):
            raise ValueError("OTP must be 4–8 digits.")
        return v


class OnboardingRequest(BaseModel):
    display_name: str | None = None
    diet: str | None = None
    cuisines: list[str] = []
    skipped: bool = False


# ── Helpers ────────────────────────────────────────────────────────────────────

def _get_client_ip(request: Request) -> str:
    """Best-effort client IP — works behind Vercel / Render proxies."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _check_otp_rate_limit(phone: str, ip: str) -> None:
    """
    Raise HTTP 429 if the phone or IP has exceeded OTP send limits.
    Checked against otp_requests table (not Supabase Auth's own limits).
    """
    now = datetime.now(timezone.utc)

    # Per-phone limit: 3 sends per 15 minutes
    phone_cutoff = (now - _OTP_PHONE_WINDOW).isoformat()
    phone_result = (
        supabase_admin
        .table("otp_requests")
        .select("id", count="exact")
        .eq("phone", phone)
        .gte("requested_at", phone_cutoff)
        .execute()
    )
    phone_count = phone_result.count or 0
    if phone_count >= _OTP_PHONE_LIMIT:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"Too many OTP requests for this number. "
                f"Please wait {_OTP_PHONE_WINDOW.seconds // 60} minutes and try again."
            ),
        )

    # Per-IP limit: 10 sends per hour
    ip_cutoff = (now - _OTP_IP_WINDOW).isoformat()
    ip_result = (
        supabase_admin
        .table("otp_requests")
        .select("id", count="exact")
        .eq("ip_address", ip)
        .gte("requested_at", ip_cutoff)
        .execute()
    )
    ip_count = ip_result.count or 0
    if ip_count >= _OTP_IP_LIMIT:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                "Too many OTP requests from your network. "
                "Please try again in an hour."
            ),
        )


def _record_otp_request(phone: str, ip: str, status_val: str = "sent") -> str:
    """Insert a row into otp_requests. Returns the new row id."""
    row_id = str(uuid4())
    supabase_admin.table("otp_requests").insert({
        "id":         row_id,
        "phone":      phone,
        "ip_address": ip,
        "status":     status_val,
    }).execute()
    return row_id


def _safe_user_response(user: dict) -> dict:
    """Strip sensitive / internal columns before returning to client."""
    safe_keys = {
        "id", "phone", "phone_verified_at", "email",
        "display_name", "city", "tier", "tier_started_at",
        "tier_expires_at", "is_early_access", "onboarding_complete",
        "metadata", "created_at",
    }
    return {k: v for k, v in user.items() if k in safe_keys}


# ── Routes ─────────────────────────────────────────────────────────────────────

@router.post("/request-otp", status_code=status.HTTP_200_OK)
def request_otp(body: OtpRequest, request: Request) -> dict[str, Any]:
    """
    Step 1 of phone auth: request an OTP to be sent to `phone`.

    - Checks rate limits (phone + IP) before calling Supabase Auth.
    - Delegates OTP generation and SMS delivery to Supabase Auth.
      Supabase Auth in turn calls the MSG91 custom SMS hook if configured.
    - Records the request in otp_requests for rate-limit bookkeeping only.
      The OTP code itself is never stored here.
    """
    ip = _get_client_ip(request)

    # Rate-limit guard — raises 429 if exceeded
    _check_otp_rate_limit(body.phone, ip)

    # Attempt OTP send via Supabase Auth
    try:
        supabase_admin.auth.sign_in_with_otp({"phone": body.phone})
    except Exception as exc:
        err_str = str(exc).lower()
        # Surface user-facing errors clearly; mask internal errors
        if "invalid" in err_str and "phone" in err_str:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Invalid phone number — check the format and try again.",
            )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OTP service temporarily unavailable. Please try again.",
        )

    # Record in otp_requests (best-effort — don't block on failure)
    try:
        _record_otp_request(body.phone, ip, "sent")
    except Exception as exc:
        print(f"[auth] otp_requests insert failed (non-fatal): {exc}")

    return {"message": "OTP sent successfully."}


@router.post("/verify-otp", status_code=status.HTTP_200_OK)
def verify_otp(body: OtpVerifyRequest, request: Request) -> dict[str, Any]:
    """
    Step 2 of phone auth: verify the OTP and return a session JWT.

    Response includes:
      - access_token  — Supabase JWT; store in localStorage on the client
      - is_new_user   — True if onboarding_complete is False (redirect to /onboarding.html)
      - user          — safe user profile dict
    """
    # Verify OTP via Supabase Auth
    try:
        auth_response = supabase_admin.auth.verify_otp(
            {"phone": body.phone, "token": body.otp, "type": "sms"}
        )
    except Exception as exc:
        err_str = str(exc).lower()
        if "invalid" in err_str or "expired" in err_str or "token" in err_str:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect or expired OTP — please try again.",
            )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Verification service temporarily unavailable.",
        )

    if not auth_response.session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Verification failed — no session returned.",
        )

    access_token = auth_response.session.access_token
    auth_id = auth_response.user.id  # Supabase auth UUID

    # Update otp_requests status to 'verified' (best-effort)
    try:
        supabase_admin.table("otp_requests") \
            .update({"status": "verified"}) \
            .eq("phone", body.phone) \
            .eq("status", "sent") \
            .execute()
    except Exception:
        pass

    # Fetch public.users row (created by handle_new_auth_user trigger)
    user_result = (
        supabase_admin
        .table("users")
        .select("*")
        .eq("auth_id", auth_id)
        .maybe_single()
        .execute()
    )

    user_row: dict | None = user_result.data

    # Trigger may not have fired yet (race on very first request) — create row manually
    if not user_row:
        try:
            insert_result = supabase_admin.table("users").insert({
                "id":                  str(uuid4()),
                "auth_id":             auth_id,
                "phone":               body.phone,
                "phone_verified_at":   datetime.now(timezone.utc).isoformat(),
                "onboarding_complete": False,
            }).execute()
            user_row = insert_result.data[0] if insert_result.data else None
        except Exception as exc:
            # Duplicate key = trigger already fired — just fetch
            print(f"[auth] users insert fallback failed: {exc}")
            user_result2 = (
                supabase_admin
                .table("users")
                .select("*")
                .eq("auth_id", auth_id)
                .maybe_single()
                .execute()
            )
            user_row = user_result2.data

    if not user_row:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not retrieve or create user record.",
        )

    # Update last_seen_at (one UPDATE per verify, not per request)
    try:
        supabase_admin.table("users") \
            .update({"last_seen_at": datetime.now(timezone.utc).isoformat()}) \
            .eq("id", user_row["id"]) \
            .execute()
    except Exception:
        pass

    is_new_user: bool = not user_row.get("onboarding_complete", False)

    return {
        "access_token": access_token,
        "token_type":   "bearer",
        "is_new_user":  is_new_user,
        "user":         _safe_user_response(user_row),
    }


@router.get("/me", status_code=status.HTTP_200_OK)
def me(user: dict = Depends(get_current_user)) -> dict[str, Any]:
    """
    Return the authenticated user's profile.
    Refreshes last_seen_at as a MAU signal (but only once per session via
    the client — the frontend sends this on app load, not on every API call).
    """
    try:
        supabase_admin.table("users") \
            .update({"last_seen_at": datetime.now(timezone.utc).isoformat()}) \
            .eq("id", user["id"]) \
            .execute()
    except Exception:
        pass

    return _safe_user_response(user)


@router.post("/onboarding", status_code=status.HTTP_200_OK)
def onboarding(
    body: OnboardingRequest,
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Save name + dietary preferences after sign-up.
    Marks onboarding_complete = TRUE regardless of whether skipped.
    The metadata JSONB field is used as the Taste DNA seed in Phase 5.
    """
    # Merge new preferences into existing metadata (don't wipe existing keys)
    existing_metadata: dict = user.get("metadata") or {}
    if body.diet:
        existing_metadata["diet"] = body.diet
    if body.cuisines:
        existing_metadata["cuisines"] = body.cuisines
    existing_metadata["onboarding_skipped"] = body.skipped

    update_payload: dict[str, Any] = {
        "onboarding_complete": True,
        "metadata": existing_metadata,
    }
    if body.display_name and body.display_name.strip():
        update_payload["display_name"] = body.display_name.strip()[:40]

    result = (
        supabase_admin
        .table("users")
        .update(update_payload)
        .eq("id", user["id"])
        .select("*")
        .single()
        .execute()
    )

    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not save onboarding data.",
        )

    return {
        "message": "Onboarding complete.",
        "user": _safe_user_response(result.data),
    }


@router.post("/logout", status_code=status.HTTP_200_OK)
def logout(user: dict = Depends(get_current_user)) -> dict[str, str]:
    """
    Revoke the current Supabase session.
    The client must also clear localStorage on its end.
    """
    # Supabase admin sign-out invalidates the session server-side.
    # We use the admin client's sign_out — it accepts a JWT directly.
    try:
        supabase_admin.auth.admin.sign_out(user["auth_id"])
    except Exception as exc:
        # Non-fatal — if Supabase fails here the client can still clear its token
        print(f"[auth] logout sign_out failed (non-fatal): {exc}")

    return {"message": "Logged out successfully."}


# ── Phase 6: cloud sync ────────────────────────────────────────────────────────

class SyncRequest(BaseModel):
    app_data: dict


@router.get("/sync", status_code=status.HTTP_200_OK)
def get_sync(user: dict = Depends(get_current_user)) -> dict[str, Any]:
    """
    Return the cloud-stored app_data for the authenticated user.

    Stored under users.metadata.app_data (JSONB).
    Returns {"app_data": {}} when no data has been pushed yet.
    """
    metadata: dict = user.get("metadata") or {}
    return {"app_data": metadata.get("app_data") or {}}


@router.post("/sync", status_code=status.HTTP_200_OK)
def post_sync(
    body: SyncRequest,
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Persist app_data for the authenticated user.

    Merges into existing metadata (other keys like diet/cuisines are preserved).
    The frontend is responsible for sending a complete, already-merged payload —
    the backend performs a shallow metadata merge only (sets metadata.app_data).
    """
    existing_metadata: dict = user.get("metadata") or {}
    existing_metadata["app_data"] = body.app_data

    supabase_admin.table("users") \
        .update({"metadata": existing_metadata}) \
        .eq("id", user["id"]) \
        .execute()

    return {"ok": True}


# ── Phase 5: feature usage gate ───────────────────────────────────────────────

class CheckLimitRequest(BaseModel):
    feature: str
    session_id: str | None = None


@router.post("/check-limit", status_code=status.HTTP_200_OK)
def check_limit_endpoint(
    body: CheckLimitRequest,
    user: dict | None = Depends(get_optional_user),
) -> dict[str, Any]:
    """
    Check and log usage for a gated feature.

    Called by the frontend before executing client-side gated features
    (Ask Chef, Pantry, Collections, Goal, Taste DNA) and before API-backed
    features (Decide, Meal Plan) where we can't gate server-side without
    touching existing routes.

    Behaviour:
    - No token / anonymous user → 200 (allow; enforcement is off for guests)
    - Token present + enforcement_enabled FALSE for their tier → 200 (allow + log)
    - Token present + enforcement_enabled TRUE + over limit → 429
    - Token present + enforcement_enabled TRUE + under limit → 200 (allow + log)

    The feature string is validated against the known features list.
    Unknown feature names → 200 (fail open, never block unknown features).
    """
    # Anonymous users — allow silently, nothing to log
    if user is None:
        return {"allowed": True, "reason": "anonymous"}

    # Validate feature name — reject obviously wrong values, but fail open for unknowns
    valid_features = {
        "decide_for_me", "ask_chef", "pantry_items",
        "collections", "meal_plan", "goal_tracking", "advanced_taste_dna",
    }
    feature = body.feature.strip()
    if feature not in valid_features:
        return {"allowed": True, "reason": "unknown_feature"}

    # check_limit() raises HTTP 429 if the user is over their limit.
    # If enforcement_enabled is FALSE (day one), it returns immediately.
    check_limit(user, feature, session_id=body.session_id)  # type: ignore[arg-type]

    # Log the usage after the gate passes
    log_usage(user, feature, session_id=body.session_id)  # type: ignore[arg-type]

    return {"allowed": True}
