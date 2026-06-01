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
_E164_RE  = re.compile(r"^\+[1-9]\d{6,14}$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PASSWORD_MIN = 8

# Where the password-reset / email-confirmation links should land the user.
# Override with APP_URL in the environment (e.g. https://simmer.app).
_APP_URL = os.getenv("APP_URL", "http://localhost:3000").rstrip("/")

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


# ── Email + password auth models ────────────────────────────────────────────────

class _EmailMixin(BaseModel):
    email: str

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        v = v.strip().lower()
        if not _EMAIL_RE.match(v) or len(v) > 254:
            raise ValueError("Enter a valid email address.")
        return v


class _PasswordMixin(BaseModel):
    password: str

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        if len(v) < _PASSWORD_MIN:
            raise ValueError(f"Password must be at least {_PASSWORD_MIN} characters.")
        if len(v) > 72:  # bcrypt hard limit used by Supabase/GoTrue
            raise ValueError("Password must be 72 characters or fewer.")
        return v


class EmailSignupRequest(_EmailMixin, _PasswordMixin):
    display_name: str | None = None


class EmailLoginRequest(_EmailMixin):
    password: str  # no strength check on login — just presence


class PasswordResetRequest(_EmailMixin):
    pass


class UpdatePasswordRequest(_PasswordMixin):
    access_token: str  # recovery token from the reset-link redirect


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


def _get_or_create_user_row(
    auth_id: str,
    *,
    email: str | None = None,
    display_name: str | None = None,
) -> dict:
    """
    Fetch the public.users row for a Supabase auth user, creating it if the
    handle_new_auth_user trigger hasn't fired yet (race on first request).
    Mirrors the phone-verify path so email + phone users are consistent.
    """
    result = (
        supabase_admin.table("users")
        .select("*").eq("auth_id", auth_id).maybe_single().execute()
    )
    user_row: dict | None = result.data

    if not user_row:
        payload: dict[str, Any] = {
            "id": str(uuid4()),
            "auth_id": auth_id,
            "onboarding_complete": False,
        }
        if email:
            payload["email"] = email
        if display_name and display_name.strip():
            payload["display_name"] = display_name.strip()[:40]
        try:
            ins = supabase_admin.table("users").insert(payload).execute()
            user_row = ins.data[0] if ins.data else None
        except Exception as exc:  # duplicate key = trigger already created it
            print(f"[auth] users insert fallback (non-fatal): {exc}")
            again = (
                supabase_admin.table("users")
                .select("*").eq("auth_id", auth_id).maybe_single().execute()
            )
            user_row = again.data

    if not user_row:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not retrieve or create user record.",
        )

    # Backfill email if the trigger created the row without it
    if email and not user_row.get("email"):
        try:
            supabase_admin.table("users").update({"email": email}) \
                .eq("id", user_row["id"]).execute()
            user_row["email"] = email
        except Exception:
            pass

    return user_row


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


# ── Email + password auth ───────────────────────────────────────────────────────

@router.post("/email-signup", status_code=status.HTTP_200_OK)
def email_signup(body: EmailSignupRequest) -> dict[str, Any]:
    """
    Create an account with email + password.

    With Supabase "Confirm email" ON, this sends a verification email and returns
    NO session — the client shows a "check your inbox" state. The user confirms,
    then signs in via /email-login.
    """
    try:
        resp = supabase_admin.auth.sign_up({
            "email": body.email,
            "password": body.password,
            "options": {"email_redirect_to": f"{_APP_URL}/login.html?verified=1"},
        })
    except Exception as exc:
        err = str(exc).lower()
        if "already" in err or "registered" in err or "exists" in err:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An account with this email already exists. Try signing in.",
            )
        if "password" in err:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Password is too weak — use at least 8 characters.",
            )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not create the account right now. Please try again.",
        )

    auth_user = getattr(resp, "user", None)
    # Provision the public.users row early so display_name/email are stored.
    if auth_user and auth_user.id:
        try:
            _get_or_create_user_row(
                str(auth_user.id), email=body.email, display_name=body.display_name
            )
        except Exception as exc:
            print(f"[auth] signup row provision failed (non-fatal): {exc}")

    # Session is only present if email confirmation is disabled.
    session = getattr(resp, "session", None)
    if session and session.access_token and auth_user:
        user_row = _get_or_create_user_row(
            str(auth_user.id), email=body.email, display_name=body.display_name
        )
        return {
            "access_token": session.access_token,
            "token_type": "bearer",
            "needs_verification": False,
            "is_new_user": True,
            "user": _safe_user_response(user_row),
        }

    return {
        "needs_verification": True,
        "message": "Account created. Check your inbox to verify your email, then sign in.",
    }


@router.post("/email-login", status_code=status.HTTP_200_OK)
def email_login(body: EmailLoginRequest) -> dict[str, Any]:
    """Sign in with email + password. Returns a session JWT on success."""
    try:
        resp = supabase_admin.auth.sign_in_with_password(
            {"email": body.email, "password": body.password}
        )
    except Exception as exc:
        err = str(exc).lower()
        if "not confirmed" in err or "confirm" in err:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Please verify your email first — check your inbox.",
            )
        # Invalid credentials → generic message (don't reveal which field is wrong)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password.",
        )

    session = getattr(resp, "session", None)
    auth_user = getattr(resp, "user", None)
    if not session or not session.access_token or not auth_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password.",
        )

    user_row = _get_or_create_user_row(str(auth_user.id), email=body.email)

    # Soft-delete guard (mirrors get_current_user)
    if user_row.get("deleted_at") is not None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account has been deactivated.",
        )

    try:
        supabase_admin.table("users") \
            .update({"last_seen_at": datetime.now(timezone.utc).isoformat()}) \
            .eq("id", user_row["id"]).execute()
    except Exception:
        pass

    return {
        "access_token": session.access_token,
        "token_type": "bearer",
        "is_new_user": not user_row.get("onboarding_complete", False),
        "user": _safe_user_response(user_row),
    }


@router.post("/request-password-reset", status_code=status.HTTP_200_OK)
def request_password_reset(body: PasswordResetRequest, request: Request) -> dict[str, Any]:
    """
    Send a password-reset email. Always returns 200 with a generic message so we
    never reveal whether an email is registered (anti-enumeration).
    """
    try:
        supabase_admin.auth.reset_password_for_email(
            body.email,
            {"redirect_to": f"{_APP_URL}/reset-password.html"},
        )
    except Exception as exc:
        # Log but still return the generic success message.
        print(f"[auth] reset_password_for_email failed (non-fatal): {exc}")

    return {"message": "If an account exists for that email, a reset link is on its way."}


@router.post("/update-password", status_code=status.HTTP_200_OK)
def update_password(body: UpdatePasswordRequest) -> dict[str, Any]:
    """
    Complete a password reset. The client passes the recovery `access_token` it
    received in the reset-link redirect (URL fragment) plus the new password.
    We resolve the user from that token, then set the new password via admin API.
    """
    try:
        auth_resp = supabase_admin.auth.get_user(body.access_token)
        auth_user = getattr(auth_resp, "user", None)
    except Exception:
        auth_user = None

    if not auth_user or not auth_user.id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="This reset link is invalid or has expired. Request a new one.",
        )

    try:
        supabase_admin.auth.admin.update_user_by_id(
            str(auth_user.id), {"password": body.password}
        )
    except Exception as exc:
        err = str(exc).lower()
        if "password" in err:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Password is too weak — use at least 8 characters.",
            )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not update the password right now. Please try again.",
        )

    return {"message": "Password updated. You can now sign in with your new password."}


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
