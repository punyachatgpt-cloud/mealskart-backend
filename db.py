"""
Simmer — Supabase data layer.

Replaces the SQLite-backed implementation. All recipe data lives in
public.recipes in Supabase (PostgreSQL), which is persistent across
Render restarts — unlike the old simmer.db ephemeral file.

The returned dict shape is identical to the previous SQLite version so
all existing callers (fastapi_app.py, seed_mealdb.py) work unchanged.
"""

from auth.supabase_client import supabase_admin

_PAGE = 2000  # well above any realistic recipe count; avoids PostgREST 1k default


def _row_to_dict(row: dict) -> dict:
    """Normalise a Supabase row to the dict shape the API expects."""
    d = dict(row)
    d["tags"] = [t.strip() for t in (d.get("tags") or "").split(",") if t.strip()]
    d["ingredients_list"] = [
        i.strip().lower()
        for i in (d.get("ingredients") or "").split(",")
        if i.strip()
    ]
    return d


def init_db() -> None:
    """No-op: schema is managed by migration.sql / Supabase dashboard."""
    pass


def upsert_recipe(recipe: dict) -> None:
    """Upsert a single recipe row into Supabase."""
    row = {k: v for k, v in recipe.items() if k != "created_at"}
    supabase_admin.table("recipes").upsert(row, on_conflict="id").execute()


def upsert_recipes_batch(recipes: list[dict]) -> None:
    """Batch upsert — far more efficient than one-by-one for seeding."""
    if not recipes:
        return
    rows = [{k: v for k, v in r.items() if k != "created_at"} for r in recipes]
    supabase_admin.table("recipes").upsert(rows, on_conflict="id").execute()


def load_all_recipes() -> list[dict]:
    result = (
        supabase_admin.table("recipes")
        .select("*")
        .order("id")
        .limit(_PAGE)
        .execute()
    )
    return [_row_to_dict(r) for r in (result.data or [])]


def count_by_source(source: str) -> int:
    result = (
        supabase_admin.table("recipes")
        .select("id")
        .eq("source", source)
        .limit(_PAGE)
        .execute()
    )
    return len(result.data or [])


def get_max_id() -> int:
    result = (
        supabase_admin.table("recipes")
        .select("id")
        .order("id", desc=True)
        .limit(1)
        .execute()
    )
    return result.data[0]["id"] if result.data else 0


def get_existing_external_ids() -> set[str]:
    result = (
        supabase_admin.table("recipes")
        .select("external_id")
        .eq("source", "mealdb")
        .neq("external_id", "")
        .limit(_PAGE)
        .execute()
    )
    return {r["external_id"] for r in (result.data or [])}


# Legacy stubs — kept so any old import doesn't crash with AttributeError
def get_connection():
    raise RuntimeError("SQLite removed — use Supabase functions in db.py instead.")
