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


class TrackRequest(BaseModel):
    action: Literal["view", "cook", "decide"]
    recipe_id: str


def load_recipes(csv_path: Path):
    recipes = []
    with csv_path.open(newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        for row in reader:
            row["time_minutes"] = int(row["time_minutes"])
            row["tags"] = [tag.strip() for tag in row["tags"].split(",") if tag.strip()]
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


def to_recipe_code(recipe_id: int) -> str:
    return f"r{recipe_id:03d}"


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

    for recipe in filtered_recipes:
        score, reasons = score_recipe(
            recipe=recipe,
            time_available=payload.time_available,
            mood=payload.mood,
        )
        score += random.uniform(0, 1)
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

    def pick_diverse(items, count):
        selected = []
        selected_ids = set()
        covered = set()
        categories = ["quick", "healthy", "comfort"]

        for category in categories:
            best = None
            for item in items:
                if item["id"] in selected_ids:
                    continue
                if category not in item.get("_tags", []):
                    continue
                # Prefer adding a new category, then higher score.
                if best is None or item["score"] > best["score"]:
                    best = item
            if best is not None and len(selected) < count:
                selected.append(best)
                selected_ids.add(best["id"])
                covered.update(best.get("_tags", []))

        # Fill remaining slots with best-scoring items (still unique).
        for item in items:
            if len(selected) >= count:
                break
            if item["id"] in selected_ids:
                continue
            selected.append(item)
            selected_ids.add(item["id"])

        # If still short, randomly fill from the full ranked list (unique only).
        if len(selected) < count:
            pool = [r for r in ranked if r["id"] not in selected_ids]
            random.shuffle(pool)
            for item in pool:
                if len(selected) >= count:
                    break
                selected.append(item)
                selected_ids.add(item["id"])

        return selected

    limit = 1 if payload.mode == "decide" else 3
    selected = pick_diverse(candidates, limit)

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
def track_interaction(payload: TrackRequest):
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
