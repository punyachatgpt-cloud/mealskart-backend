"""
FastAPI dependency: get_current_user()

Validates the Bearer JWT issued by Supabase Auth by calling
supabase_admin.auth.get_user(token) — this approach works with any JWT
signing algorithm Supabase uses (ES256/ECC P-256, HS256, future rotations)
without needing to hard-code a secret or algorithm.

Usage in a route:
    @router.get("/me")
    def me(user: dict = Depends(get_current_user)):
        return user

Raises HTTP 401 for missing, malformed, or expired tokens.
Raises HTTP 403 if the user account has been soft-deleted.
"""

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .supabase_client import supabase_admin

_bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict:
    """
    Verify the Supabase JWT via the Auth API (algorithm-agnostic),
    then load and return the public.users row.
    """
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated — provide Authorization: Bearer <token>",
        )

    token = credentials.credentials

    # ── 1. Verify token via Supabase Auth (handles ES256, HS256, key rotation) ─
    try:
        auth_response = supabase_admin.auth.get_user(token)
        auth_user = auth_response.user
    except Exception as exc:
        err = str(exc).lower()
        if "expired" in err or "invalid" in err or "not found" in err:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has expired or is invalid — please sign in again.",
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not verify token.",
        )

    if not auth_user or not auth_user.id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing user identity.",
        )

    auth_id: str = str(auth_user.id)

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
