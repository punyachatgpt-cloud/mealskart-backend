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

# Alphabetical fetch covers all ~300 TheMealDB free-tier recipes in 26 requests.
# The old FETCH_CATEGORIES / FETCH_AREAS / MAX_PER_CATEGORY approach is replaced.

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



async def _fetch_by_letter(client: httpx.AsyncClient, letter: str) -> list[dict]:
    """
    Fetch all full meal objects starting with `letter` using search.php?f=.
    Returns complete meal objects — no second lookup needed.
    """
    for attempt in range(3):
        try:
            resp = await client.get(
                f"{MEALDB_BASE}/search.php?f={letter}",
                timeout=httpx.Timeout(45.0),
            )
            resp.raise_for_status()
            return resp.json().get("meals") or []
        except httpx.TimeoutException:
            if attempt < 2:
                await asyncio.sleep(2 ** attempt)
                continue
            print(f"[seed]   TIMEOUT letter={letter} after 3 attempts, skipping.")
            return []
        except Exception as exc:
            print(f"[seed]   ERROR letter={letter}: {exc}")
            return []
    return []


async def seed_from_mealdb(force: bool = False) -> int:
    """
    Fetch every recipe in TheMealDB using the alphabetical search endpoint
    (search.php?f=a … ?f=z). Each letter request returns full meal objects
    with all details — no secondary lookup needed. This gives ~300 recipes
    in just 26 API calls, vs the old category/area approach of 400+ calls.

    MealDB recipes receive integer IDs starting at 1001.
    Idempotent — skips already-imported meals unless force=True.
    """
    existing_ext_ids: set[str] = set() if force else get_existing_external_ids()
    next_id  = max(get_max_id(), 1000) + 1
    inserted = 0

    letters = "abcdefghijklmnopqrstuvwxyz"
    print(f"[seed] TheMealDB: fetching all recipes via a-z alphabetical search "
          f"({len(existing_ext_ids)} already seeded)...")

    async with httpx.AsyncClient(timeout=httpx.Timeout(45.0)) as client:
        for letter in letters:
            meals = await _fetch_by_letter(client, letter)
            if not meals:
                await asyncio.sleep(0.3)
                continue

            new_meals = [m for m in meals
                         if str(m.get("idMeal", "")).strip() not in existing_ext_ids]

            if not new_meals:
                print(f"[seed]   {letter}: {len(meals)} meals, all already seeded")
                await asyncio.sleep(0.2)
                continue

            print(f"[seed]   {letter}: {len(new_meals)} new / {len(meals)} total")

            batch: list[dict] = []
            for meal in new_meals:
                meal_id = str(meal.get("idMeal", "")).strip()
                if not meal_id:
                    continue

                # Use the meal's own category/area — more accurate than filter hints
                real_cat  = (meal.get("strCategory") or "Miscellaneous").strip()
                real_area = (meal.get("strArea")     or "Unknown").strip()

                recipe = _meal_to_recipe(meal, real_cat, real_area, next_id)
                if recipe is None:
                    continue

                batch.append(recipe)
                existing_ext_ids.add(meal_id)
                next_id  += 1
                inserted += 1

            if batch:
                upsert_recipes_batch(batch)

            await asyncio.sleep(0.3)   # stay well within free-tier rate limits

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
