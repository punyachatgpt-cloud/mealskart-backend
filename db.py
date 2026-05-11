"""
Simmer — SQLite data layer.

Schema keeps a single `recipes` table that holds both:
  - CSV recipes  (id 1-50,   source='csv')
  - TheMealDB    (id 1001+,  source='mealdb')

All endpoints continue to use the same dict shape:
  id, name, diet, time_minutes, calories, difficulty, category,
  tags (list), ingredients_list (list), steps (str, semicolon-separated),
  image_url, source, external_id
"""

import sqlite3
from pathlib import Path
from typing import Optional

DB_PATH = Path(__file__).resolve().parent / "simmer.db"


# ── Connection ────────────────────────────────────────────────────────────────

def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    # Enable WAL for better concurrent reads during background seeding
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


# ── Schema ────────────────────────────────────────────────────────────────────

def init_db() -> None:
    """Create schema if it doesn't exist yet. Safe to call multiple times."""
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS recipes (
            id           INTEGER PRIMARY KEY,
            name         TEXT    NOT NULL,
            diet         TEXT    NOT NULL DEFAULT 'veg',
            time_minutes INTEGER NOT NULL DEFAULT 30,
            calories     INTEGER          DEFAULT 0,
            difficulty   TEXT             DEFAULT 'easy',
            category     TEXT             DEFAULT 'other',
            tags         TEXT             DEFAULT '',
            ingredients  TEXT             DEFAULT '',
            steps        TEXT             DEFAULT '',
            image_url    TEXT             DEFAULT '',
            source       TEXT             DEFAULT 'csv',
            external_id  TEXT             DEFAULT ''
        );

        CREATE INDEX IF NOT EXISTS idx_diet      ON recipes(diet);
        CREATE INDEX IF NOT EXISTS idx_category  ON recipes(category);
        CREATE INDEX IF NOT EXISTS idx_time      ON recipes(time_minutes);
        CREATE INDEX IF NOT EXISTS idx_source    ON recipes(source);
    """)
    conn.commit()
    conn.close()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _row_to_dict(row: sqlite3.Row) -> dict:
    """Convert a SQLite row to the dict shape the API expects."""
    d = dict(row)
    # tags: "quick,healthy" → ["quick", "healthy"]
    d["tags"] = [t.strip() for t in (d.get("tags") or "").split(",") if t.strip()]
    # ingredients_list mirrors the CSV-era field name
    d["ingredients_list"] = [
        i.strip().lower()
        for i in (d.get("ingredients") or "").split(",")
        if i.strip()
    ]
    return d


# ── CRUD ──────────────────────────────────────────────────────────────────────

def upsert_recipe(conn: sqlite3.Connection, recipe: dict) -> None:
    """Insert or replace a recipe row.  Caller owns commit/close."""
    conn.execute(
        """
        INSERT INTO recipes
            (id, name, diet, time_minutes, calories, difficulty, category,
             tags, ingredients, steps, image_url, source, external_id)
        VALUES
            (:id, :name, :diet, :time_minutes, :calories, :difficulty, :category,
             :tags, :ingredients, :steps, :image_url, :source, :external_id)
        ON CONFLICT(id) DO UPDATE SET
            name         = excluded.name,
            diet         = excluded.diet,
            time_minutes = excluded.time_minutes,
            calories     = excluded.calories,
            difficulty   = excluded.difficulty,
            category     = excluded.category,
            tags         = excluded.tags,
            ingredients  = excluded.ingredients,
            steps        = excluded.steps,
            image_url    = excluded.image_url,
            source       = excluded.source,
            external_id  = excluded.external_id
        """,
        recipe,
    )


def load_all_recipes() -> list[dict]:
    conn = get_connection()
    rows = conn.execute("SELECT * FROM recipes ORDER BY id").fetchall()
    conn.close()
    return [_row_to_dict(r) for r in rows]


def get_recipe_by_id(recipe_id: int) -> Optional[dict]:
    conn = get_connection()
    row = conn.execute("SELECT * FROM recipes WHERE id = ?", (recipe_id,)).fetchone()
    conn.close()
    return _row_to_dict(row) if row else None


def count_recipes() -> int:
    conn = get_connection()
    n = conn.execute("SELECT COUNT(*) FROM recipes").fetchone()[0]
    conn.close()
    return n


def count_by_source(source: str) -> int:
    conn = get_connection()
    n = conn.execute(
        "SELECT COUNT(*) FROM recipes WHERE source = ?", (source,)
    ).fetchone()[0]
    conn.close()
    return n


def get_max_id() -> int:
    conn = get_connection()
    val = conn.execute("SELECT MAX(id) FROM recipes").fetchone()[0]
    conn.close()
    return val or 0


def get_existing_external_ids() -> set[str]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT external_id FROM recipes WHERE source = 'mealdb' AND external_id != ''"
    ).fetchall()
    conn.close()
    return {r[0] for r in rows}
