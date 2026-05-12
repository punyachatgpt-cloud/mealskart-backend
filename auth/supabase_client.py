"""
Supabase client singleton.

Two clients are exposed:
  - supabase_admin  — uses SERVICE_ROLE_KEY; bypasses RLS; used server-side only
  - supabase_anon   — uses ANON_KEY; respects RLS; not used server-side for writes

Both are created once at import time and reused across requests.
"""

import os

from dotenv import load_dotenv
from supabase import Client, create_client

load_dotenv()

_url: str | None = os.getenv("SUPABASE_URL")
_service_key: str | None = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
_anon_key: str | None = os.getenv("SUPABASE_ANON_KEY")

if not _url or not _service_key:
    raise RuntimeError(
        "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set. "
        "Copy .env.example → .env and fill in your Supabase project credentials."
    )

# Admin client — server-side only, bypasses RLS
supabase_admin: Client = create_client(_url, _service_key)

# Anon client — available if ever needed for RLS-scoped reads
supabase_anon: Client = create_client(_url, _anon_key or "")
