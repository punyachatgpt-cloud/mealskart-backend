import asyncio
import csv
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

import db as _db


app = FastAPI(title="Recipe Recommender API")


ENRICHED_RECIPES = {
    1: {
        "servings": 1,
        "nutrition": {"protein_g": 7, "carbs_g": 44, "fat_g": 9, "fiber_g": 4},
        "ingredients_with_quantities": [
            {"name": "poha", "quantity": 0.75, "unit": "cup"},
            {"name": "onion", "quantity": 0.25, "unit": "cup"},
            {"name": "green chili", "quantity": 1, "unit": "piece"},
            {"name": "peanuts", "quantity": 2, "unit": "tbsp"},
            {"name": "curry leaves", "quantity": 6, "unit": "leaves"},
            {"name": "mustard seeds", "quantity": 0.5, "unit": "tsp"},
            {"name": "turmeric", "quantity": 0.25, "unit": "tsp"},
            {"name": "lemon", "quantity": 0.5, "unit": "piece"},
            {"name": "oil", "quantity": 1, "unit": "tsp"},
        ],
        "substitutions": {
            "lemon": ["amchur", "lime"],
            "peanuts": ["roasted chana", "cashews"],
            "green chili": ["black pepper", "red chili flakes"],
        },
    },
    2: {
        "servings": 1,
        "nutrition": {"protein_g": 11, "carbs_g": 29, "fat_g": 7, "fiber_g": 6},
        "ingredients_with_quantities": [
            {"name": "besan", "quantity": 0.5, "unit": "cup"},
            {"name": "onion", "quantity": 0.25, "unit": "cup"},
            {"name": "tomato", "quantity": 0.25, "unit": "cup"},
            {"name": "green chili", "quantity": 1, "unit": "piece"},
            {"name": "coriander", "quantity": 2, "unit": "tbsp"},
            {"name": "oil", "quantity": 1, "unit": "tsp"},
        ],
        "substitutions": {
            "besan": ["moong dal batter", "oats flour"],
            "green chili": ["black pepper", "red chili powder"],
        },
    },
    3: {
        "servings": 1,
        "nutrition": {"protein_g": 8, "carbs_g": 38, "fat_g": 7, "fiber_g": 2},
        "ingredients_with_quantities": [
            {"name": "cooked rice", "quantity": 1, "unit": "cup"},
            {"name": "curd", "quantity": 0.5, "unit": "cup"},
            {"name": "milk", "quantity": 2, "unit": "tbsp"},
            {"name": "ginger", "quantity": 0.5, "unit": "tsp"},
            {"name": "mustard seeds", "quantity": 0.5, "unit": "tsp"},
        ],
        "substitutions": {
            "curd": ["Greek yogurt", "plant yogurt"],
            "cooked rice": ["millet", "brown rice"],
        },
    },
    10: {
        "servings": 1,
        "nutrition": {"protein_g": 18, "carbs_g": 12, "fat_g": 19, "fiber_g": 3},
        "ingredients_with_quantities": [
            {"name": "paneer", "quantity": 100, "unit": "g"},
            {"name": "onion", "quantity": 0.25, "unit": "cup"},
            {"name": "tomato", "quantity": 0.25, "unit": "cup"},
            {"name": "green chili", "quantity": 1, "unit": "piece"},
            {"name": "oil", "quantity": 1, "unit": "tsp"},
        ],
        "substitutions": {
            "paneer": ["tofu", "scrambled egg"],
            "green chili": ["black pepper", "red chili flakes"],
        },
    },
    31: {
        "servings": 1,
        "nutrition": {"protein_g": 27, "carbs_g": 9, "fat_g": 8, "fiber_g": 2},
        "ingredients_with_quantities": [
            {"name": "tuna", "quantity": 100, "unit": "g"},
            {"name": "onion", "quantity": 0.25, "unit": "cup"},
            {"name": "tomato", "quantity": 0.25, "unit": "cup"},
            {"name": "garlic", "quantity": 1, "unit": "clove"},
            {"name": "oil", "quantity": 1, "unit": "tsp"},
        ],
        "substitutions": {
            "tuna": ["boiled egg", "chicken breast"],
            "tomato": ["tomato puree", "curd"],
        },
    },
}

DEFAULT_NUTRITION = {"protein_g": 0, "carbs_g": 0, "fat_g": 0, "fiber_g": 0}


class RecommendRequest(BaseModel):
    time_available: int
    mood: Literal["quick", "healthy", "comfort"]
    diet: Literal["veg", "non-veg"]
    mode: Literal["normal", "decide"] = "normal"
    ingredients: list[str] | None = None
    category: str | None = None
    name_query: str | None = None   # free-text: filter by name or key ingredient


class TrackRequest(BaseModel):
    action: Literal["view", "cook", "decide"]
    recipe_id: str


class MealPlanRequest(BaseModel):
    days: int = 7
    meals_per_day: int = 2
    time_available: int = 30
    diet: Literal["veg", "non-veg"]
    mood: Literal["quick", "healthy", "comfort"] | None = None
    category: str | None = None


def load_recipes(csv_path: Path):
    recipes = []
    with csv_path.open(newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        for row in reader:
            # Normalize header keys (handles UTF-8 BOM in the first column name).
            row = {str(k).lstrip("\ufeff").strip().strip('"'): v for k, v in row.items()}
            row["time_minutes"] = int(row["time_minutes"])
            row["calories"] = int(row.get("calories") or 0)
            row["difficulty"] = (row.get("difficulty") or "easy").strip().lower()
            row["tags"] = [tag.strip() for tag in row["tags"].split(",") if tag.strip()]
            ingredients_raw = row.get("ingredients", "") or ""
            row["ingredients_list"] = [
                ingredient.strip().lower()
                for ingredient in str(ingredients_raw).split(",")
                if ingredient.strip()
            ]
            row["category"] = (row.get("category") or "other").strip().lower()
            recipes.append(row)
    return recipes


def score_recipe(recipe, time_available: int, mood: str):
    score = 0
    reasons = []

    if recipe["time_minutes"] <= time_available:
        score += 1
        reasons.append(f"fits within {time_available} minutes")

    if mood in recipe["tags"]:
        score += 1
        reasons.append(f"matches {mood} mood")

    if "quick" in recipe["tags"] and time_available <= 15:
        score += 1
        reasons.append("extra quick bonus for short time")

    return score, reasons


def normalize_category(category: str | None) -> str | None:
    if not category:
        return None
    normalized = category.strip().lower().replace("_", "-")
    return None if normalized in {"", "all", "any"} else normalized


def to_recipe_code(recipe_id: int) -> str:
    return f"r{recipe_id:03d}"


def parse_tracked_recipe_id(recipe_id: str) -> int | None:
    rid = (recipe_id or "").strip().lower()
    if rid.startswith("r") and rid[1:].isdigit():
        return int(rid[1:])
    if rid.isdigit():
        return int(rid)
    return None


def build_reason(tags: list[str], time_minutes: int, time_available: int) -> str:
    parts = []

    if "quick" in tags:
        parts.append("⚡ Quick to prepare.")
    if "healthy" in tags:
        parts.append("🥗 Healthy choice.")
    if "comfort" in tags:
        parts.append("🍲 Comfort food.")

    if time_minutes <= time_available:
        parts.append(f"Ready in under {time_available} mins.")

    reason = " ".join(parts).strip()
    return reason if reason else "A good match for your preferences."


def ingredient_match_percent(recipe_ingredients: list[str], user_ingredients: set[str] | None) -> int:
    if not recipe_ingredients or not user_ingredients:
        return 0
    matching = sum(
        1 for ri in recipe_ingredients
        if any(ui in ri or ri in ui for ui in user_ingredients)
    )
    return round((matching / len(recipe_ingredients)) * 100)


def _name_query_matches(recipe: dict, query: str) -> bool:
    """
    True if the recipe name or ingredients satisfy the query.

    Strategy (in order of decreasing strictness):
    1. Exact phrase  — "butter chicken" in "Butter Chicken (Murgh Makhani)"  ✓
    2. All words     — every word in query appears somewhere in name+ingredients
                       "butter" AND "chicken" both found                       ✓
    3. Any word      — fallback for single-word queries (already exact above)
    """
    q = query.strip().lower()
    if not q:
        return True

    name_lower = recipe["name"].lower()
    all_text   = name_lower + " " + " ".join(recipe.get("ingredients_list", []))

    # 1. Exact phrase match (handles single-word queries too)
    if q in all_text:
        return True

    # 2. All words present anywhere in name+ingredients (handles "butter chicken")
    words = q.split()
    if len(words) > 1 and all(w in all_text for w in words):
        return True

    return False


def get_recipe_enrichment(recipe) -> dict:
    recipe_id = int(recipe["id"])
    enrichment = ENRICHED_RECIPES.get(recipe_id)
    if enrichment:
        return enrichment

    return {
        "servings": 1,
        "nutrition": DEFAULT_NUTRITION,
        "ingredients_with_quantities": [
            {"name": ingredient, "quantity": None, "unit": ""}
            for ingredient in recipe.get("ingredients_list", [])
        ],
        "substitutions": {},
    }


def recipe_summary(recipe) -> dict:
    enrichment = get_recipe_enrichment(recipe)
    return {
        "id": int(recipe["id"]),
        "name": recipe["name"],
        "time_minutes": recipe["time_minutes"],
        "calories": recipe["calories"],
        "servings": enrichment["servings"],
        "nutrition": enrichment["nutrition"],
        "difficulty": recipe["difficulty"],
        "diet": recipe["diet"],
        "tags": recipe["tags"],
        "category": recipe.get("category", "other"),
        "image_url": recipe.get("image_url", ""),
        "ingredients_preview": recipe.get("ingredients_list", [])[:5],
        "ingredients_with_quantities": enrichment["ingredients_with_quantities"][:5],
    }


CSV_PATH = Path(__file__).resolve().parent / "recipes.csv"
INDEX_PATH = Path(__file__).resolve().parent / "index.html"
interactions = []
recent_suggestions = []
user_preferences = {
    "quick": 0,
    "healthy": 0,
    "comfort": 0,
    "veg": 0,
    "non-veg": 0,
}


@app.on_event("startup")
async def load_recipes_on_startup():
    """
    Startup sequence:
      1. Init SQLite schema (instant).
      2. Seed CSV data synchronously so the API is ready immediately.
      3. Load all recipes into app.state.recipes.
      4. Kick off TheMealDB seeding as a background task — once done,
         app.state.recipes is refreshed to include the new recipes.
    Falls back gracefully to CSV-only if TheMealDB is unreachable.
    """
    from seed_mealdb import seed_from_csv, seed_from_mealdb

    _db.init_db()

    # Always re-seed CSV so new rows (added after initial deploy) are picked up.
    # seed_from_csv uses upsert — safe to call every startup, takes < 1 second.
    seed_from_csv(force=True)

    # Serve requests immediately with whatever is in the DB
    app.state.recipes = _db.load_all_recipes()
    print(f"[startup] Loaded {len(app.state.recipes)} recipes from DB.")

    # Enrich with TheMealDB data in the background (non-blocking)
    async def _bg_mealdb_seed():
        try:
            added = await seed_from_mealdb()
            if added > 0:
                app.state.recipes = _db.load_all_recipes()
                print(f"[startup] Refreshed recipe list: {len(app.state.recipes)} total.")
        except Exception as exc:
            print(f"[startup] TheMealDB background seed failed (non-fatal): {exc}")

    try:
        asyncio.create_task(_bg_mealdb_seed())
    except RuntimeError:
        # No running event loop (e.g. sync test client) — skip background seed
        pass


def get_loaded_recipes(request: Request):
    return getattr(request.app.state, "recipes", [])


@app.get("/")
def home():
    return FileResponse(INDEX_PATH)


@app.get("/search")
def search_recipes(q: str, diet: str = "", limit: int = 6, request: Request = None):
    """
    Pure text search ranked by relevance.
    Completely separate from /recommend — no mood/time scoring, no explore-exploit,
    no recent_suggestions filtering.  Returns up to `limit` best matches.

    Relevance tiers (higher = better):
      100 — exact name match
       80 — name starts with query
       60 — query is a phrase inside the name
       50 — all query words appear in name (handles "butter chicken")
       30 — any query word appears in name
       20 — query phrase found in ingredients
       10 — any query word found in ingredients

    Diet is a soft preference: matching diet gets +5 but non-matching results
    are still returned as fallback (so veg users CAN still see Butter Chicken).
    """
    recipes = get_loaded_recipes(request)
    q_lower = (q or "").strip().lower()
    if len(q_lower) < 2:
        return []

    words = [w for w in q_lower.split() if w]
    scored: list[tuple[int, dict]] = []

    for recipe in recipes:
        name_lower = recipe["name"].lower()
        ing_text   = " ".join(recipe.get("ingredients_list", []))
        all_text   = name_lower + " " + ing_text

        # ── Name matching (priority 1) ─────────────────────────────────────
        if q_lower == name_lower:
            score = 100
        elif name_lower.startswith(q_lower):
            score = 80
        elif q_lower in name_lower:
            score = 60
        elif len(words) > 1 and all(w in name_lower for w in words):
            score = 50
        elif any(w in name_lower for w in words):
            score = 30
        # ── Ingredient matching (priority 2) ──────────────────────────────
        elif q_lower in ing_text:
            score = 20
        elif len(words) > 1 and all(w in ing_text for w in words):
            score = 15
        elif any(w in ing_text for w in words):
            score = 10
        else:
            continue  # no match

        # Soft diet preference boost (not a hard filter)
        if diet and recipe["diet"].strip().lower() == diet.strip().lower():
            score += 5

        scored.append((score, recipe))

    # Sort: relevance desc, then name asc for stable ordering
    scored.sort(key=lambda x: (-x[0], x[1]["name"]))

    return [recipe_summary(r) for _, r in scored[:limit]]


@app.post("/recommend")
def recommend(payload: RecommendRequest, request: Request):
    ranked = []
    recipes = get_loaded_recipes(request)
    diet = payload.diet
    category = normalize_category(payload.category)

    cook_counts = {}
    for event in interactions:
        if event.get("action") == "cook":
            recipe_code = event.get("recipe_id")
            cook_counts[recipe_code] = cook_counts.get(recipe_code, 0) + 1

    filtered_recipes = [
        r for r in recipes
        if r["diet"].strip().lower() == diet.strip().lower()
    ]

    if not filtered_recipes:
        return []

    # Prefer respecting the user's time limit; if too strict, fall back to diet-only.
    time_filtered_recipes = [r for r in filtered_recipes if int(r["time_minutes"]) <= payload.time_available]
    if time_filtered_recipes:
        filtered_recipes = time_filtered_recipes

    # Category guides intent, but falls back gracefully when too narrow.
    if category:
        category_filtered_recipes = [
            r for r in filtered_recipes
            if (r.get("category") or "").strip().lower() == category
        ]
        if category_filtered_recipes:
            filtered_recipes = category_filtered_recipes

    # Name / key-ingredient query — e.g. "butter chicken", "pasta", "biryani".
    # Applied before the ingredient-tag filter so it works standalone.
    name_query = (payload.name_query or "").strip().lower()
    name_query_active = bool(name_query)
    name_query_found  = False
    if name_query:
        # First try within already-filtered pool (diet + time + category)
        name_filtered = [r for r in filtered_recipes if _name_query_matches(r, name_query)]
        # Broaden: ignore time/category/diet filters — search all recipes
        if not name_filtered:
            name_filtered = [r for r in recipes if _name_query_matches(r, name_query)]
        if name_filtered:
            filtered_recipes = name_filtered
            name_query_found = True
        else:
            # Nothing found anywhere — return empty so the frontend shows "no results"
            filtered_recipes = []

    # Optional ingredient-based filtering (>= 30% of recipe ingredients match via substring).
    normalized_user_ingredients = None
    if payload.ingredients:
        normalized_user_ingredients = {
            str(i).strip().lower() for i in payload.ingredients if str(i).strip()
        }

    ingredient_match_ids: set[int] = set()
    if normalized_user_ingredients:
        ingredient_filtered = []
        single_ing_mode = len(normalized_user_ingredients) <= 2
        # For multi-ingredient pantry searches use 30% threshold.
        # For single/double ingredient searches use 10% so at least 1 match suffices.
        threshold = 0.1 if single_ing_mode else 0.3

        for r in filtered_recipes:
            recipe_ingredients = r.get("ingredients_list", [])
            if not recipe_ingredients:
                continue
            # Substring matching: "pork" matches "pork belly", "pork chops", etc.
            matching = sum(
                1 for ri in recipe_ingredients
                if any(ui in ri or ri in ui for ui in normalized_user_ingredients)
            )
            match_score = matching / len(recipe_ingredients)

            # In single-ingredient mode also accept a recipe whose NAME contains
            # the ingredient — e.g. "Barbecue pork buns" has no 'pork' in its
            # ingredient list, but the name makes the intent clear.
            name_hit = single_ing_mode and any(
                ui in r["name"].lower() for ui in normalized_user_ingredients
            )

            if match_score >= threshold or name_hit:
                ingredient_filtered.append(r)
                ingredient_match_ids.add(int(r["id"]))

        if ingredient_filtered:
            filtered_recipes = ingredient_filtered
        elif single_ing_mode and normalized_user_ingredients:
            # Nothing found even with name matching — broaden search across all
            # diet-matching recipes (ignore time/category) before giving up.
            broader = [
                r for r in recipes
                if r["diet"].strip().lower() == diet.strip().lower()
                and (
                    any(
                        ui in ri or ri in ui
                        for ri in r.get("ingredients_list", [])
                        for ui in normalized_user_ingredients
                    )
                    or any(ui in r["name"].lower() for ui in normalized_user_ingredients)
                )
            ]
            if broader:
                filtered_recipes = broader
                ingredient_match_ids = {int(r["id"]) for r in broader}

    for recipe in filtered_recipes:
        enrichment = get_recipe_enrichment(recipe)
        score, reasons = score_recipe(
            recipe=recipe,
            time_available=payload.time_available,
            mood=payload.mood,
        )
        score += random.uniform(0, 1)

        # Small personalization bonus based on learned preferences.
        preference_bonus = 0.0
        for tag in recipe.get("tags", []):
            preference_bonus += min(user_preferences.get(tag, 0), 10) * 0.5
        preference_bonus += min(user_preferences.get(recipe.get("diet", ""), 0), 10) * 0.5
        score += preference_bonus

        # Ingredient match boost (only when ingredient filtering is active).
        if normalized_user_ingredients and int(recipe["id"]) in ingredient_match_ids:
            score += 2
        if category and (recipe.get("category") or "").strip().lower() == category:
            score += 1.5
            reasons.append(f"matches {category.replace('-', ' ')} preference")
        cook_count = cook_counts.get(to_recipe_code(int(recipe["id"])), 0)
        if cook_count > 0:
            score -= cook_count * 0.5
            reasons.append(f"penalized for repeat cooking ({cook_count} past cooks)")

        ranked.append(
            {
                "id": int(recipe["id"]),
                "name": recipe["name"],
                "time_minutes": recipe["time_minutes"],
                "calories": recipe["calories"],
                "servings": enrichment["servings"],
                "nutrition": enrichment["nutrition"],
                "difficulty": recipe["difficulty"],
                "image_url": recipe.get("image_url", ""),
                "ingredients_preview": recipe.get("ingredients_list", [])[:5],
                "ingredients_with_quantities": enrichment["ingredients_with_quantities"][:5],
                "ingredient_match_percent": ingredient_match_percent(
                    recipe.get("ingredients_list", []),
                    normalized_user_ingredients,
                ),
                "tags": ", ".join(recipe["tags"]),
                "category": recipe.get("category", "other"),
                "_tags": recipe["tags"],
                "score": score,
                "why": "; ".join(reasons) if reasons else "best available option",
            }
        )

    ranked.sort(key=lambda item: (-item["score"], item["time_minutes"], item["name"]))

    global recent_suggestions
    candidates = [r for r in ranked if r["id"] not in recent_suggestions]
    if not candidates:
        candidates = ranked[:]

    limit = 1 if payload.mode == "decide" else 3

    # Exploration vs exploitation:
    # - Take top 5 candidates by score
    # - Pick 2 best (exploit)
    # - Pick 1 random from the remaining 3 (explore)
    sorted_recipes = sorted(candidates, key=lambda x: x["score"], reverse=True)
    top_candidates = sorted_recipes[:5]

    def select_explore_exploit(items, count):
        if not items:
            return []

        selected = []
        selected_ids = set()
        covered_categories = set()
        categories = {"quick", "healthy", "comfort"}

        def add_item(item):
            selected.append(item)
            selected_ids.add(item["id"])
            covered_categories.update(set(item.get("_tags", [])) & categories)

        # Exploit: first pick is the best.
        add_item(items[0])

        # Exploit: second pick prefers adding a new category if possible.
        if count >= 2:
            second = None
            for item in items[1:]:
                if item["id"] in selected_ids:
                    continue
                item_categories = set(item.get("_tags", [])) & categories
                if item_categories and not item_categories.issubset(covered_categories):
                    second = item
                    break
            if second is None:
                for item in items[1:]:
                    if item["id"] not in selected_ids:
                        second = item
                        break
            if second is not None:
                add_item(second)

        # Explore: pick one random from the remaining top candidates, preferring new categories.
        if count >= 3:
            remaining = [i for i in items[2:] if i["id"] not in selected_ids]
            if remaining:
                diverse = []
                for item in remaining:
                    item_categories = set(item.get("_tags", [])) & categories
                    if item_categories and not item_categories.issubset(covered_categories):
                        diverse.append(item)
                pool = diverse if diverse else remaining
                add_item(random.choice(pool))

        # Fill to count with best-scoring unique items.
        if len(selected) < count:
            for item in sorted_recipes:
                if len(selected) >= count:
                    break
                if item["id"] in selected_ids:
                    continue
                add_item(item)

        # Final fallback: fill from the full ranked list (even if recently suggested) to guarantee count.
        if len(selected) < count:
            pool = [r for r in ranked if r["id"] not in selected_ids]
            random.shuffle(pool)
            for item in pool:
                if len(selected) >= count:
                    break
                add_item(item)

        return selected[:count]

    selected = select_explore_exploit(top_candidates, limit) if limit == 3 else select_explore_exploit(top_candidates, 1)

    # Maintain last 5 suggestion ids to avoid repetition.
    recent_suggestions.extend([r["id"] for r in selected])
    recent_suggestions = recent_suggestions[-5:]

    # Shuffle before returning to reduce over-prioritizing a single item.
    random.shuffle(selected)

    for item in selected:
        item["reason"] = build_reason(
            tags=item.get("_tags", []),
            time_minutes=int(item["time_minutes"]),
            time_available=int(payload.time_available),
        )
        item.pop("_tags", None)

    return selected


@app.get("/recipe/{id}")
def get_recipe(id: int, request: Request):
    recipes = get_loaded_recipes(request)
    recipe = next((item for item in recipes if int(item["id"]) == id), None)
    if recipe is None:
        raise HTTPException(status_code=404, detail="Recipe not found")

    enrichment = get_recipe_enrichment(recipe)
    steps = [step.strip() for step in recipe["steps"].split(";") if step.strip()]
    return {
        "id": int(recipe["id"]),
        "name": recipe["name"],
        "ingredients": recipe.get("ingredients_list", []),
        "ingredients_with_quantities": enrichment["ingredients_with_quantities"],
        "time_minutes": recipe["time_minutes"],
        "calories": recipe["calories"],
        "servings": enrichment["servings"],
        "nutrition": enrichment["nutrition"],
        "substitutions": enrichment["substitutions"],
        "difficulty": recipe["difficulty"],
        "diet": recipe["diet"],
        "tags": recipe["tags"],
        "category": recipe.get("category", "other"),
        "image_url": recipe.get("image_url", ""),
        "steps": steps,
    }


@app.post("/meal-plan")
def meal_plan(payload: MealPlanRequest, request: Request):
    recipes = get_loaded_recipes(request)
    days_count = max(1, min(int(payload.days), 7))
    meals_per_day = max(1, min(int(payload.meals_per_day), 3))
    category = normalize_category(payload.category)

    candidates = [
        r for r in recipes
        if r["diet"].strip().lower() == payload.diet.strip().lower()
        and int(r["time_minutes"]) <= int(payload.time_available)
    ]

    if category:
        category_matches = [
            r for r in candidates
            if (r.get("category") or "").strip().lower() == category
        ]
        if category_matches:
            candidates = category_matches

    if payload.mood:
        candidates.sort(
            key=lambda r: (
                payload.mood not in r.get("tags", []),
                int(r["time_minutes"]),
                r["name"],
            )
        )
    else:
        candidates.sort(key=lambda r: (int(r["time_minutes"]), r["name"]))

    if not candidates:
        return {"days": [], "grocery_list": [], "total_calories": 0}

    needed = days_count * meals_per_day
    selected = candidates[:needed]
    grocery_counts = {}
    total_calories = 0
    days = []

    for day_index in range(days_count):
        start = day_index * meals_per_day
        day_recipes = selected[start:start + meals_per_day]
        if not day_recipes:
            break

        for recipe in day_recipes:
            total_calories += int(recipe["calories"])
            for ingredient in recipe.get("ingredients_list", []):
                grocery_counts[ingredient] = grocery_counts.get(ingredient, 0) + 1

        days.append(
            {
                "day": day_index + 1,
                "recipes": [recipe_summary(recipe) for recipe in day_recipes],
            }
        )

    grocery_list = [
        {"name": name, "used_in": count}
        for name, count in sorted(grocery_counts.items(), key=lambda item: (-item[1], item[0]))
    ]

    return {
        "days": days,
        "grocery_list": grocery_list,
        "total_calories": total_calories,
    }


@app.post("/track")
def track_interaction(payload: TrackRequest, request: Request):
    if payload.action == "cook":
        tracked_id = parse_tracked_recipe_id(payload.recipe_id)
        if tracked_id is not None:
            recipes = get_loaded_recipes(request)
            recipe = next((r for r in recipes if int(r["id"]) == tracked_id), None)
            if recipe is not None:
                for tag in recipe.get("tags", []):
                    if tag in user_preferences:
                        user_preferences[tag] += 1
                diet = (recipe.get("diet") or "").strip().lower()
                if diet in user_preferences:
                    user_preferences[diet] += 1

    interaction = {
        "action": payload.action,
        "recipe_id": payload.recipe_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    interactions.append(interaction)
    return interaction


@app.get("/interactions")
def get_interactions():
    return interactions
