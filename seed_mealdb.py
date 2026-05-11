"""
Simmer database seeder.

Seeds recipes from two sources:
  1. CSV    — recipes.csv (ids 1-50, always seeded first, fast)
  2. MealDB — TheMealDB free public API, no key needed (ids 1001+)

Usage
-----
  # One-time / CI / manual refresh
  python seed_mealdb.py

  # From FastAPI startup (non-blocking)
  from seed_mealdb import seed_from_csv, seed_from_mealdb
  seed_from_csv()                       # sync, fast
  await seed_from_mealdb()              # async, runs in background
"""

import asyncio
import csv
import re
from pathlib import Path
from typing import Optional

import httpx

from db import (
    count_by_source,
    get_connection,
    get_existing_external_ids,
    get_max_id,
    init_db,
    upsert_recipe,
)

CSV_PATH    = Path(__file__).resolve().parent / "recipes.csv"
MEALDB_BASE = "https://www.themealdb.com/api/json/v1/1"

# Categories to pull from TheMealDB.
# Keeping this focused keeps the startup seed time under ~60 seconds.
FETCH_CATEGORIES = [
    "Chicken", "Seafood", "Beef", "Lamb",
    "Vegetarian", "Vegan", "Pasta", "Breakfast", "Side", "Starter",
]
MAX_PER_CATEGORY = 12   # max meals fetched per category

# ── Lookup tables ─────────────────────────────────────────────────────────────

VEG_CATEGORIES     = {"Vegetarian", "Vegan", "Pasta", "Side", "Breakfast", "Starter", "Dessert"}
NON_VEG_CATEGORIES = {"Chicken", "Beef", "Seafood", "Lamb", "Pork", "Goat"}

# TheMealDB category → Simmer category (overridden by area when available)
CATEGORY_MAP: dict[str, str] = {
    "Chicken":    "continental",
    "Beef":       "north-indian",
    "Seafood":    "south-indian",
    "Lamb":       "north-indian",
    "Pork":       "continental",
    "Goat":       "north-indian",
    "Pasta":      "continental",
    "Vegetarian": "north-indian",
    "Vegan":      "north-indian",
    "Side":       "north-indian",
    "Breakfast":  "continental",
    "Starter":    "snacks",
    "Dessert":    "continental",
}

# TheMealDB area → Simmer category (more specific than category)
AREA_MAP: dict[str, str] = {
    "Indian":     "north-indian",
    "Chinese":    "chinese",
    "Italian":    "continental",
    "French":     "continental",
    "American":   "continental",
    "British":    "continental",
    "Thai":       "continental",
    "Japanese":   "continental",
    "Mexican":    "continental",
    "Greek":      "continental",
    "Moroccan":   "north-indian",
    "Egyptian":   "north-indian",
    "Spanish":    "continental",
    "Portuguese": "continental",
    "Croatian":   "continental",
    "Jamaican":   "continental",
    "Malaysian":  "chinese",
    "Vietnamese": "chinese",
    "Filipino":   "chinese",
    "Canadian":   "continental",
    "Russian":    "continental",
    "Turkish":    "north-indian",
    "Kenyan":     "north-indian",
    "Tunisian":   "north-indian",
    "Unknown":    "other",
}

TIME_EST: dict[str, int] = {
    "Chicken": 25, "Beef": 35, "Seafood": 20, "Lamb": 35, "Pork": 30, "Goat": 35,
    "Pasta": 25, "Vegetarian": 20, "Vegan": 20, "Side": 20,
    "Breakfast": 15, "Starter": 15, "Dessert": 25,
}

CALORIE_EST: dict[str, int] = {
    "Chicken": 320, "Beef": 380, "Seafood": 240, "Lamb": 360, "Pork": 360, "Goat": 350,
    "Pasta": 380, "Vegetarian": 250, "Vegan": 220, "Side": 180,
    "Breakfast": 280, "Starter": 200, "Dessert": 400,
}


# ── Normalisation helpers ─────────────────────────────────────────────────────

def _derive_tags(mdb_cat: str, time_min: int) -> str:
    tags: list[str] = []
    if time_min <= 15:
        tags.append("quick")
    if mdb_cat in {"Vegetarian", "Vegan", "Seafood", "Side", "Starter"}:
        tags.append("healthy")
    if mdb_cat in {"Beef", "Chicken", "Lamb", "Pasta", "Pork", "Goat", "Dessert", "Breakfast"}:
        tags.append("comfort")
    return ",".join(tags) if tags else "comfort"


def _parse_ingredients(meal: dict) -> str:
    """Extract strIngredient1-20 into a comma-separated string."""
    parts: list[str] = []
    for i in range(1, 21):
        ing = (meal.get(f"strIngredient{i}") or "").strip()
        if ing:
            parts.append(ing)
    return ", ".join(parts)


def _parse_steps(instructions: str) -> str:
    """
    Turn MealDB's free-text instructions into a semicolon-separated step list
    that matches the existing CSV format the frontend expects.
    """
    if not instructions:
        return ""

    text = re.sub(r"\r\n|\r", "\n", instructions)

    # Split on existing newlines first
    lines = [l.strip() for l in text.split("\n") if len(l.strip()) > 8]

    # If paragraph-style, split on sentence boundaries
    if len(lines) < 3:
        sentences = re.split(r"(?<=[.!?])\s+", text)
        lines = [s.strip() for s in sentences if len(s.strip()) > 8]

    # Strip leading "1.", "Step 2:", "STEP 3 -" etc.
    cleaned: list[str] = []
    for line in lines:
        line = re.sub(r"^(step\s*)?\d+[\.\)\:\-]\s*", "", line, flags=re.IGNORECASE)
        line = line.strip()
        if line:
            cleaned.append(line)

    # Cap at 12 steps, join with semicolon (same as CSV)
    return "; ".join(cleaned[:12])


# ── CSV seeder ────────────────────────────────────────────────────────────────

def seed_from_csv(force: bool = False) -> int:
    """
    Seed recipes.csv into SQLite, preserving original integer IDs (1-50).
    Idempotent — skips if CSV records already exist (unless force=True).
    """
    if not force and count_by_source("csv") > 0:
        print(f"[seed] CSV already seeded ({count_by_source('csv')} rows), skipping.")
        return 0

    conn = get_connection()
    count = 0
    with CSV_PATH.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Strip BOM and stray quotes from headers
            row = {str(k).lstrip("﻿").strip().strip('"'): v for k, v in row.items()}
            recipe = {
                "id":           int(row["id"]),
                "name":         row["name"].strip(),
                "diet":         row["diet"].strip().lower(),
                "time_minutes": int(row["time_minutes"]),
                "calories":     int(row.get("calories") or 0),
                "difficulty":   (row.get("difficulty") or "easy").strip().lower(),
                "category":     (row.get("category")   or "other").strip().lower(),
                "tags":         row.get("tags", "").strip(),
                "ingredients":  row.get("ingredients", "").strip(),
                "steps":        row.get("steps", "").strip(),
                "image_url":    "",
                "source":       "csv",
                "external_id":  "",
            }
            upsert_recipe(conn, recipe)
            count += 1

    conn.commit()
    conn.close()
    print(f"[seed] Seeded {count} recipes from CSV.")
    return count


# ── MealDB seeder ─────────────────────────────────────────────────────────────

async def seed_from_mealdb(force: bool = False) -> int:
    """
    Async: fetch recipes from TheMealDB public API and insert into SQLite.
    MealDB recipes receive integer IDs starting at 1001.
    Idempotent — skips already-imported meals unless force=True.
    """
    existing_ext_ids: set[str] = set() if force else get_existing_external_ids()
    next_id = max(get_max_id(), 1000) + 1
    inserted = 0

    print(f"[seed] Starting TheMealDB fetch ({len(FETCH_CATEGORIES)} categories, "
          f"max {MAX_PER_CATEGORY} per category)…")

    async with httpx.AsyncClient(timeout=httpx.Timeout(20.0)) as client:
        for category in FETCH_CATEGORIES:
            # ── 1. Fetch the meal list for this category ──────────────────
            try:
                resp = await client.get(f"{MEALDB_BASE}/filter.php?c={category}")
                resp.raise_for_status()
                basic_meals: list[dict] = (resp.json().get("meals") or [])[:MAX_PER_CATEGORY]
            except Exception as exc:
                print(f"[seed]   ✗ category {category}: {exc}")
                continue

            print(f"[seed]   {category}: {len(basic_meals)} meals to process")

            # ── 2. Fetch details for each meal ────────────────────────────
            for basic in basic_meals:
                meal_id = str(basic.get("idMeal", "")).strip()
                if not meal_id:
                    continue
                if meal_id in existing_ext_ids:
                    continue  # already in DB

                await asyncio.sleep(0.08)   # ~12 req/s — well within free-tier limits

                try:
                    r2 = await client.get(f"{MEALDB_BASE}/lookup.php?i={meal_id}")
                    r2.raise_for_status()
                    details_list = r2.json().get("meals") or []
                    if not details_list:
                        continue
                    meal = details_list[0]
                except Exception as exc:
                    print(f"[seed]     ✗ meal {meal_id}: {exc}")
                    continue

                name = (meal.get("strMeal") or "").strip()
                if not name:
                    continue

                area      = (meal.get("strArea") or "Unknown").strip()
                time_min  = TIME_EST.get(category, 25)
                diet      = "non-veg" if category in NON_VEG_CATEGORIES else "veg"
                sim_cat   = AREA_MAP.get(area, CATEGORY_MAP.get(category, "other"))

                recipe = {
                    "id":           next_id,
                    "name":         name,
                    "diet":         diet,
                    "time_minutes": time_min,
                    "calories":     CALORIE_EST.get(category, 280),
                    "difficulty":   "medium",
                    "category":     sim_cat,
                    "tags":         _derive_tags(category, time_min),
                    "ingredients":  _parse_ingredients(meal),
                    "steps":        _parse_steps(meal.get("strInstructions", "")),
                    "image_url":    meal.get("strMealThumb", ""),
                    "source":       "mealdb",
                    "external_id":  meal_id,
                }

                conn = get_connection()
                upsert_recipe(conn, recipe)
                conn.commit()
                conn.close()

                existing_ext_ids.add(meal_id)
                next_id  += 1
                inserted += 1

    print(f"[seed] TheMealDB: inserted {inserted} new recipes (total DB now "
          f"~{inserted + count_by_source('csv')} rows).")
    return inserted


# ── Combined entry point ──────────────────────────────────────────────────────

async def seed_db(force: bool = False) -> None:
    """
    Full seed: CSV first (sync), then TheMealDB (async).
    Safe to call multiple times — idempotent by default.
    Pass force=True to re-seed everything from scratch.
    """
    init_db()
    seed_from_csv(force=force)
    await seed_from_mealdb(force=force)


if __name__ == "__main__":
    import sys
    force = "--force" in sys.argv
    asyncio.run(seed_db(force=force))
