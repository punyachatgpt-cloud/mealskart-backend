import csv
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel


app = FastAPI(title="Recipe Recommender API")


class RecommendRequest(BaseModel):
    time_available: int
    mood: Literal["quick", "healthy", "comfort"]
    diet: Literal["veg", "non-veg"]
    mode: Literal["normal", "decide"] = "normal"
    ingredients: list[str] | None = None
    category: str | None = None


class TrackRequest(BaseModel):
    action: Literal["view", "cook", "decide"]
    recipe_id: str


def load_recipes(csv_path: Path):
    recipes = []
    with csv_path.open(newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        for row in reader:
            # Normalize header keys (handles UTF-8 BOM in the first column name).
            row = {str(k).lstrip("\ufeff").strip().strip('"'): v for k, v in row.items()}
            row["time_minutes"] = int(row["time_minutes"])
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
def load_recipes_on_startup():
    app.state.recipes = load_recipes(CSV_PATH)


def get_loaded_recipes(request: Request):
    return getattr(request.app.state, "recipes", [])


@app.get("/")
def home():
    return FileResponse(INDEX_PATH)


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
    print("FILTERED COUNT:", len(filtered_recipes))

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

    # Optional ingredient-based filtering (>= 50% of recipe ingredients match).
    normalized_user_ingredients = None
    if payload.ingredients:
        normalized_user_ingredients = {
            str(i).strip().lower() for i in payload.ingredients if str(i).strip()
        }

    ingredient_match_ids: set[int] = set()
    if normalized_user_ingredients:
        ingredient_filtered = []
        for r in filtered_recipes:
            recipe_ingredients = set(r.get("ingredients_list", []))
            if not recipe_ingredients:
                continue
            matching = len(recipe_ingredients & normalized_user_ingredients)
            match_score = matching / len(recipe_ingredients)
            if match_score >= 0.5:
                ingredient_filtered.append(r)
                ingredient_match_ids.add(int(r["id"]))

        # Fallback: if no ingredient matches, continue with normal filtered set.
        if ingredient_filtered:
            filtered_recipes = ingredient_filtered

    for recipe in filtered_recipes:
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

    steps = [step.strip() for step in recipe["steps"].split(";") if step.strip()]
    return {
        "name": recipe["name"],
        "steps": steps,
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

    print("Preferences:", user_preferences)
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
