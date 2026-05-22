"""
Simmer — Supabase data layer.

Replaces the SQLite-backed implementation. All recipe data lives in
public.recipes in Supabase (PostgreSQL), which is persistent across
Render restarts — unlike the old simmer.db ephemeral file.

The returned dict shape is identical to the previous SQLite version so
all existing callers (fastapi_app.py, seed_mealdb.py) work unchanged.

Interactions table (run once in Supabase SQL editor to enable persistence):

    CREATE TABLE IF NOT EXISTS interactions (
        id        BIGSERIAL PRIMARY KEY,
        action    TEXT        NOT NULL,
        recipe_id TEXT,
        timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
"""

from datetime import datetime, timezone

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


# ── Interactions (personalization) ───────────────────────────────────────────

def save_interaction(action: str, recipe_id) -> dict:
    """
    Persist a user interaction to Supabase.
    Fails silently if the interactions table hasn't been created yet —
    call is always safe to make, personalisation simply won't survive restarts
    until the table exists.
    """
    row = {
        "action":    action,
        "recipe_id": str(recipe_id) if recipe_id is not None else None,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    try:
        result = supabase_admin.table("interactions").insert(row).execute()
        return result.data[0] if result.data else row
    except Exception as exc:
        # Table may not exist yet — gracefully degrade to in-memory only
        print(f"[db] interactions insert skipped ({exc.__class__.__name__}): {exc}")
        return row


def load_recent_interactions(limit: int = 500) -> list[dict]:
    """
    Load the most recent interactions from Supabase, oldest-first so they can
    be replayed in order to rebuild user_preferences.
    Returns [] if the table doesn't exist or any other error occurs.
    """
    try:
        result = (
            supabase_admin.table("interactions")
            .select("action, recipe_id, timestamp")
            .order("timestamp", desc=True)
            .limit(limit)
            .execute()
        )
        rows = result.data or []
        return list(reversed(rows))  # oldest first for preference replay
    except Exception as exc:
        print(f"[db] interactions load skipped ({exc.__class__.__name__}): {exc}")
        return []


def fix_mealdb_difficulty(calc_fn) -> int:
    """
    One-time migration: recompute difficulty for every MealDB recipe using
    the current _calc_difficulty logic and update it in Supabase.
    Returns the number of rows updated.
    """
    try:
        result = (
            supabase_admin.table("recipes")
            .select("id, steps, time_minutes")
            .eq("source", "mealdb")
            .limit(2000)
            .execute()
        )
        rows = result.data or []
        if not rows:
            return 0
        updates = [
            {"id": r["id"], "difficulty": calc_fn(r.get("steps", ""), r.get("time_minutes", 25))}
            for r in rows
        ]
        supabase_admin.table("recipes").upsert(updates, on_conflict="id").execute()
        print(f"[db] Recomputed difficulty for {len(updates)} MealDB recipes.")
        return len(updates)
    except Exception as exc:
        print(f"[db] fix_mealdb_difficulty skipped ({exc.__class__.__name__}): {exc}")
        return 0


def fix_mealdb_categories() -> int:
    """
    One-time migration: correct the most egregious wrong category mappings
    for existing MealDB records.  Uses Supabase filter chains — no raw SQL needed.
    Returns the number of individual update calls made.
    """
    # (wrong_category, correct_category, name_keywords_that_confirm_wrong_origin)
    FIXES = [
        # North-African / Middle-Eastern cuisine mislabelled as north-indian
        ("north-indian", "continental", ["Moroccan", "Egyptian", "Tunisian", "Kenyan", "Turkish"]),
        # South-East Asian cuisine mislabelled as chinese
        ("chinese",      "continental", ["Malaysian", "Vietnamese", "Filipino"]),
    ]
    count = 0
    try:
        for wrong_cat, right_cat, keywords in FIXES:
            for kw in keywords:
                supabase_admin.table("recipes") \
                    .update({"category": right_cat}) \
                    .eq("source", "mealdb") \
                    .eq("category", wrong_cat) \
                    .ilike("name", f"%{kw}%") \
                    .execute()
                count += 1
        print(f"[db] Category fix: executed {count} targeted update(s).")
        return count
    except Exception as exc:
        print(f"[db] fix_mealdb_categories skipped ({exc.__class__.__name__}): {exc}")
        return 0


# Legacy stubs — kept so any old import doesn't crash with AttributeError
def get_connection():
    raise RuntimeError("SQLite removed — use Supabase functions in db.py instead.")
