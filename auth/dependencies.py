"""
FastAPI dependency: get_current_user()

Validates the Bearer JWT issued by Supabase Auth, looks up the matching
public.users row, and returns it as a plain dict.

Usage in a route:
    @router.get("/me")
    def me(user: dict = Depends(get_current_user)):
        return user

Raises HTTP 401 for missing, malformed, or expired tokens.
Raises HTTP 403 if the user account has been soft-deleted.
"""

import os

from dotenv import load_dotenv
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import ExpiredSignatureError, JWTError, jwt

from .supabase_client import supabase_admin

load_dotenv()

_JWT_SECRET: str = os.getenv("SUPABASE_JWT_SECRET", "")
_JWT_ALGORITHM = "HS256"
_JWT_AUDIENCE = "authenticated"

_bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict:
    """
    Decode the Supabase JWT, verify signature + expiry, load public.users.
    Returns the users row as a dict.
    """
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated — provide Authorization: Bearer <token>",
        )

    token = credentials.credentials

    if not _JWT_SECRET:
        raise RuntimeError(
            "SUPABASE_JWT_SECRET is not configured. "
            "Set it in .env (Supabase Dashboard → Settings → API → JWT Secret)."
        )

    # ── 1. Decode and verify JWT ─────────────────────────────────────────────
    try:
        payload = jwt.decode(
            token,
            _JWT_SECRET,
            algorithms=[_JWT_ALGORITHM],
            audience=_JWT_AUDIENCE,
        )
    except ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired — please sign in again.",
        )
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {exc}",
        )

    auth_id: str | None = payload.get("sub")
    if not auth_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing 'sub' claim.",
        )

    # ── 2. Load public.users row ─────────────────────────────────────────────
    result = (
        supabase_admin
        .table("users")
        .select("*")
        .eq("auth_id", auth_id)
        .single()
        .execute()
    )

    if not result.data:
        # Row should have been created by the handle_new_auth_user trigger.
        # If it's missing, the token is valid but the user row is absent —
        # treat as unauthenticated until the row is created.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User record not found — please sign up.",
        )

    user = result.data

    # ── 3. Soft-delete guard ─────────────────────────────────────────────────
    if user.get("deleted_at") is not None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account has been deactivated.",
        )

    return user


def get_optional_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict | None:
    """
    Like get_current_user but returns None instead of raising 401.
    Use for endpoints that work for both authenticated and anonymous users.
    """
    if not credentials:
        return None
    try:
        return get_current_user(credentials)
    except HTTPException:
        return None
