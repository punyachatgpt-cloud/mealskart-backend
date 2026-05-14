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
    get_existing_external_ids,
    get_max_id,
    init_db,
    upsert_recipes_batch,
)

CSV_PATH    = Path(__file__).resolve().parent / "recipes.csv"
MEALDB_BASE = "https://www.themealdb.com/api/json/v1/1"

# ── What to fetch ────────────────────────────────────────────────────────────
# Category-based fetch (strCategory)
FETCH_CATEGORIES = [
    "Chicken", "Seafood", "Beef", "Lamb", "Pork",
    "Vegetarian", "Vegan", "Pasta", "Breakfast", "Side", "Starter", "Miscellaneous",
]
# Area-based fetch (strArea) — gives authentic regional recipes
# TheMealDB endpoint: filter.php?a=Chinese  (same shape as category filter)
# Note: not all areas have meals on the free API — verified working list below
FETCH_AREAS = [
    "Chinese", "Japanese", "Mexican", "Italian",
    "American", "British", "Thai", "Moroccan",
    "French", "Greek", "Spanish", "Canadian",
]
MAX_PER_CATEGORY = 20   # max meals fetched per category/area

# ── Lookup tables ─────────────────────────────────────────────────────────────

VEG_CATEGORIES     = {"Vegetarian", "Vegan", "Pasta", "Side", "Breakfast", "Starter", "Dessert"}
NON_VEG_CATEGORIES = {"Chicken", "Beef", "Seafood", "Lamb", "Pork", "Goat"}

# For area-based fetch, diet is determined from the meal's category in the detail response
# These area tags map to diet and simmer-category
AREA_DIET_DEFAULT: dict[str, str] = {
    "Indian": "veg",       # will be overridden per recipe based on category
    "Chinese": "non-veg",
    "Japanese": "non-veg",
    "Mexican": "non-veg",
    "Italian": "veg",
    "American": "non-veg",
    "British": "non-veg",
    "Thai": "non-veg",
    "Moroccan": "non-veg",
}

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
    Seed recipes.csv into Supabase, preserving original integer IDs (1-50).
    Idempotent — skips if CSV records already exist (unless force=True).
    """
    if not force and count_by_source("csv") > 0:
        print(f"[seed] CSV already seeded ({count_by_source('csv')} rows), skipping.")
        return 0

    if not CSV_PATH.exists():
        print("[seed] recipes.csv not found — skipping CSV seed (data already in Supabase).")
        return 0

    batch: list[dict] = []
    with CSV_PATH.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            row = {str(k).lstrip("﻿").strip().strip('"'): v for k, v in row.items()}
            batch.append({
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
            })

    upsert_recipes_batch(batch)
    print(f"[seed] Seeded {len(batch)} recipes from CSV into Supabase.")
    return len(batch)


# ── MealDB seeder ─────────────────────────────────────────────────────────────

def _meal_to_recipe(meal: dict, hint_category: str, hint_area: str, simmer_id: int) -> dict | None:
    """
    Normalise a TheMealDB full meal object into a Simmer recipe dict.
    hint_category / hint_area are the filter values used to find this meal.
    The recipe's actual strCategory / strArea override them where available.
    """
    name = (meal.get("strMeal") or "").strip()
    if not name:
        return None

    # Prefer the actual category from the recipe over the filter hint
    real_cat  = (meal.get("strCategory") or hint_category).strip()
    real_area = (meal.get("strArea")     or hint_area).strip()

    # Diet: driven by real category
    if real_cat in VEG_CATEGORIES:
        diet = "veg"
    elif real_cat in NON_VEG_CATEGORIES:
        diet = "non-veg"
    else:
        diet = AREA_DIET_DEFAULT.get(real_area, "non-veg")

    time_min  = TIME_EST.get(real_cat,     TIME_EST.get(hint_category,     25))
    calories  = CALORIE_EST.get(real_cat,  CALORIE_EST.get(hint_category, 280))
    sim_cat   = AREA_MAP.get(real_area,    CATEGORY_MAP.get(real_cat, "other"))
    tags      = _derive_tags(real_cat, time_min)

    # MealDB thumbnail — append /preview for a smaller (300px) version
    thumb = (meal.get("strMealThumb") or "").strip()

    return {
        "id":           simmer_id,
        "name":         name,
        "diet":         diet,
        "time_minutes": time_min,
        "calories":     calories,
        "difficulty":   "medium",
        "category":     sim_cat,
        "tags":         tags,
        "ingredients":  _parse_ingredients(meal),
        "steps":        _parse_steps(meal.get("strInstructions", "")),
        "image_url":    thumb,
        "source":       "mealdb",
        "external_id":  str(meal.get("idMeal", "")),
    }


async def _fetch_meal_list(client: httpx.AsyncClient, filter_type: str, value: str) -> list[dict]:
    """Fetch meal list by category (c=) or area (a=), limited to MAX_PER_CATEGORY."""
    param = "c" if filter_type == "category" else "a"
    for attempt in range(3):
        try:
            resp = await client.get(
                f"{MEALDB_BASE}/filter.php?{param}={value}",
                timeout=httpx.Timeout(45.0),   # area lists can be large
            )
            resp.raise_for_status()
            return (resp.json().get("meals") or [])[:MAX_PER_CATEGORY]
        except httpx.TimeoutException:
            if attempt < 2:
                await asyncio.sleep(2 ** attempt)  # backoff: 1s, 2s
                continue
            print(f"[seed]   TIMEOUT {filter_type}={value} after 3 attempts, skipping.")
            return []
        except Exception as exc:
            print(f"[seed]   ERROR {filter_type}={value}: {exc}")
            return []
    return []


async def seed_from_mealdb(force: bool = False) -> int:
    """
    Async: fetch recipes from TheMealDB public API and insert into SQLite.
    Pulls from both categories AND geographic areas for wide variety.
    MealDB recipes receive integer IDs starting at 1001.
    Idempotent — skips already-imported meals unless force=True.
    """
    existing_ext_ids: set[str] = set() if force else get_existing_external_ids()
    next_id   = max(get_max_id(), 1000) + 1
    inserted  = 0

    # Build a combined fetch plan: (filter_type, value, hint_category, hint_area)
    fetch_plan: list[tuple[str, str, str, str]] = []
    for cat in FETCH_CATEGORIES:
        fetch_plan.append(("category", cat, cat, "Unknown"))
    for area in FETCH_AREAS:
        fetch_plan.append(("area", area, "Miscellaneous", area))

    print(f"[seed] TheMealDB: {len(fetch_plan)} fetch groups "
          f"({len(FETCH_CATEGORIES)} categories + {len(FETCH_AREAS)} areas), "
          f"max {MAX_PER_CATEGORY} each...")

    async with httpx.AsyncClient(timeout=httpx.Timeout(25.0)) as client:
        for filter_type, value, hint_cat, hint_area in fetch_plan:
            basic_meals = await _fetch_meal_list(client, filter_type, value)
            if not basic_meals:
                continue

            new_count = sum(
                1 for b in basic_meals
                if str(b.get("idMeal", "")).strip() not in existing_ext_ids
            )
            if new_count == 0:
                print(f"[seed]   {filter_type}={value}: all {len(basic_meals)} already seeded")
                continue

            print(f"[seed]   {filter_type}={value}: {new_count}/{len(basic_meals)} new meals")

            batch: list[dict] = []
            for basic in basic_meals:
                meal_id = str(basic.get("idMeal", "")).strip()
                if not meal_id or meal_id in existing_ext_ids:
                    continue

                await asyncio.sleep(0.08)   # gentle rate limit (~12 req/s)

                try:
                    r2 = await client.get(f"{MEALDB_BASE}/lookup.php?i={meal_id}")
                    r2.raise_for_status()
                    details_list = r2.json().get("meals") or []
                    if not details_list:
                        continue
                    meal_detail = details_list[0]
                except Exception as exc:
                    print(f"[seed]     SKIP meal {meal_id}: {exc}")
                    continue

                recipe = _meal_to_recipe(meal_detail, hint_cat, hint_area, next_id)
                if recipe is None:
                    continue

                batch.append(recipe)
                existing_ext_ids.add(meal_id)
                next_id  += 1
                inserted += 1

            # Batch upsert the whole category at once (1 API call vs N)
            if batch:
                upsert_recipes_batch(batch)

    total = count_by_source("mealdb")
    print(f"[seed] TheMealDB done: {inserted} new recipes inserted "
          f"(total MealDB in DB: {total}).")
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
