#!/usr/bin/env python3
"""
Clean up recipes.image_url — assign a correct, varied, per-dish image.

Why: the original MealDB seed stored wrong/shared photos (e.g. "Lassi" got a
meat-pie photo identical to "Classic Tourtière"). This rewrites image_url so each
recipe shows a topically-correct image, with variety within a category.

Resolution order, per recipe:
  1. --mealdb (optional): look the dish up on TheMealDB by name → use its real
     photo if the names clearly match (gives a real per-dish photo).
  2. Map the name to a curated category → pick a deterministic image from that
     category's pool (varied: different dishes in a category get different images).
  3. If the recipe already has a real (non-broken) photo and we don't recognise
     it (a genuine foreign dish), keep that photo.
  4. Otherwise a generic food image.

The frontend's recipeImg() trusts any "images.unsplash.com" URL we write here,
so after this runs the varied per-dish images show immediately.

Usage (from the mealskart-backend/ directory, with .env containing Supabase creds):
    python scripts/fix_recipe_images.py --dry-run            # preview only
    python scripts/fix_recipe_images.py --apply              # write to Supabase
    python scripts/fix_recipe_images.py --apply --mealdb     # also use TheMealDB (slower)
    python scripts/fix_recipe_images.py --apply --force      # overwrite even good photos
"""
from __future__ import annotations

import argparse
import hashlib
import os
import sys
import time

import httpx
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv()

from auth.supabase_client import supabase_admin  # noqa: E402

# ── Curated category image pools (Unsplash photo ids) ────────────────────────
# A few images per category so different dishes in the same category vary.
CATEGORY_POOLS: dict[str, list[str]] = {
    "potato":   ["photo-1631515243349-e0cb75fb8d3a", "photo-1518977676601-b53f82aba655", "photo-1552332386-f8dd00dc2f85"],
    "paneer":   ["photo-1567188040759-fb8a883dc6d8", "photo-1601050690597-df0568f70950", "photo-1631452180519-c014fe946bc7"],
    "dal":      ["photo-1585937421612-70a008356fbe", "photo-1546833999-b9f581a1996d", "photo-1564894809611-1742fc40ed80"],
    "curry":    ["photo-1604908176997-125f25cc6f3d", "photo-1631292784640-2b24be784d5d", "photo-1455619452474-d2be8b1e70cd"],
    "biryani":  ["photo-1563379091339-03b21ab4a4f8", "photo-1589302168068-964664d93dc0", "photo-1631515243349-e0cb75fb8d3a"],
    "rice":     ["photo-1536304929831-ee1ca9d44906", "photo-1516684732162-798a0062be99", "photo-1603133872878-684f208fb84b"],
    "bread":    ["photo-1565557623262-b51c2513a641", "photo-1610057099431-d73a1c9d2f2f", "photo-1574894709920-11b28e7367e3"],
    "southidli":["photo-1540189549336-e6e99c3679fe", "photo-1668236543090-82eba5ee5976", "photo-1630383249896-424e482df921"],
    "chicken":  ["photo-1600891964599-f61ba0e24092", "photo-1610057099443-fdd4fa6d6b4f", "photo-1604908554007-c9a09d76eee3"],
    "seafood":  ["photo-1559847844-5315695dadae", "photo-1580476262798-bddd9f4b7369", "photo-1535140728325-a4d3707eee61"],
    "egg":      ["photo-1525351484163-7529414344d8", "photo-1482049016688-2d3e1b311543", "photo-1607103058027-4c5a5a1f1f01"],
    "soup":     ["photo-1547592166-23ac45744acd", "photo-1604152135912-04a022e23696", "photo-1543339308-43e59d6b73a6"],
    "salad":    ["photo-1512621776951-a57141f2eefd", "photo-1546069901-ba9599a7e63c", "photo-1540420773420-3366772f4999"],
    "drink":    ["photo-1525385133512-2f3bdd039054", "photo-1600271886742-f049cd451bba", "photo-1556679343-c7306c1976bc"],
    "dessert":  ["photo-1565299624946-b28f40a0ae38", "photo-1606313564200-e75d5e30476c", "photo-1488477181946-6428a0291777"],
    "noodles":  ["photo-1481931098730-318b6f776db0", "photo-1612927601601-6638404737ce", "photo-1552611052-33e04de081de"],
    "pasta":    ["photo-1555949258-eb67b1ef0ceb", "photo-1473093295043-cdd812d0e601", "photo-1563379926898-05f4575a45d8"],
    "snack":    ["photo-1601050690597-df0568f70950", "photo-1606491956689-2ea866880c84", "photo-1626074353765-517a681e40be"],
}

# Keyword (whole word in dish name) → category. Order doesn't matter; first match wins.
KEYWORD_CATEGORY: dict[str, str] = {}
def _kw(cat: str, *words: str):
    for w in words:
        KEYWORD_CATEGORY[w] = cat

_kw("potato", "aloo", "potato", "gobi", "cauliflower", "palak", "spinach", "bhindi", "okra",
    "mushroom", "sabji", "sabzi", "bhaji", "vegetable", "veg", "baingan", "brinjal")
_kw("paneer", "paneer", "tofu")
_kw("dal", "dal", "daal", "lentil", "chana", "chickpea", "rajma", "moong", "sambar", "kadhi")
_kw("curry", "curry", "masala", "makhani", "korma", "kofta", "matar", "keema", "gravy", "saag", "rogan")
_kw("biryani", "biryani", "pulao", "pulav")
_kw("rice", "rice", "khichdi", "khichuri", "pongal")
_kw("bread", "roti", "chapati", "naan", "paratha", "puri", "poori", "kulcha", "bhatura", "thepla")
_kw("southidli", "idli", "dosa", "uttapam", "upma", "poha", "vada", "appam")
_kw("chicken", "chicken", "mutton", "lamb", "beef", "pork", "kebab", "tikka", "tandoori", "murgh")
_kw("seafood", "fish", "prawn", "prawns", "shrimp", "crab", "machli", "macher")
_kw("egg", "egg", "omelette", "omelet", "anda", "bhurji")
_kw("soup", "soup", "broth", "rasam", "shorba")
_kw("salad", "salad", "raita", "sprouts", "kachumber")
_kw("drink", "lassi", "smoothie", "juice", "shake", "chai", "tea", "coffee", "sharbat", "thandai")
_kw("dessert", "halwa", "kheer", "payasam", "ladoo", "laddoo", "barfi", "gulab", "jamun",
    "jalebi", "rasgulla", "rasmalai", "gajar", "peda", "sandesh", "modak", "mithai", "kulfi",
    "sheer", "phirni", "sweet", "cake", "pudding", "custard")
_kw("noodles", "noodle", "noodles", "ramen", "chowmein", "hakka", "schezwan")
_kw("pasta", "pasta", "spaghetti", "penne", "lasagna", "lasagne", "macaroni")
_kw("snack", "samosa", "pakora", "chaat", "tikki", "cutlet", "roll", "sandwich", "frankie",
    "kachori", "bhel", "sev")


def unsplash(pid: str, w: int = 900) -> str:
    return f"https://images.unsplash.com/{pid}?auto=format&fit=crop&w={w}&q=82"


def category_for(name: str) -> str | None:
    words = "".join(c if c.isalpha() or c.isspace() else " " for c in (name or "").lower()).split()
    for word in words:
        if word in KEYWORD_CATEGORY:
            return KEYWORD_CATEGORY[word]
    return None


def pick_from_pool(pool: list[str], key: str) -> str:
    h = int(hashlib.md5(key.encode("utf-8")).hexdigest(), 16)
    return pool[h % len(pool)]


GENERIC_POOL = [
    "photo-1546069901-ba9599a7e63c", "photo-1565299624946-b28f40a0ae38",
    "photo-1504674900247-0877df9cc836", "photo-1565958011703-44f9829ba187",
]


def mealdb_image(name: str, client: httpx.Client) -> str | None:
    try:
        r = client.get("https://www.themealdb.com/api/json/v1/1/search.php", params={"s": name}, timeout=15)
        meals = (r.json() or {}).get("meals") or []
        if not meals:
            return None
        # Only accept if the names clearly match (avoid the original mismatch bug).
        want = "".join(ch for ch in name.lower() if ch.isalnum())
        for m in meals:
            got = "".join(ch for ch in (m.get("strMeal") or "").lower() if ch.isalnum())
            if got and (got in want or want in got):
                return m.get("strMealThumb")
    except Exception:
        return None
    return None


def resolve_image(recipe: dict, *, use_mealdb: bool, force: bool, client: httpx.Client | None) -> str:
    name = recipe.get("name") or ""
    existing = recipe.get("image_url") or ""

    if use_mealdb and client is not None:
        real = mealdb_image(name, client)
        if real:
            return real

    cat = category_for(name)
    if cat and cat in CATEGORY_POOLS:
        return unsplash(pick_from_pool(CATEGORY_POOLS[cat], f"{recipe.get('id')}|{name}"))

    # Unrecognised dish: keep an existing real photo unless forcing.
    if not force and existing.startswith("http"):
        return existing

    return unsplash(pick_from_pool(GENERIC_POOL, name or str(recipe.get("id"))))


def main() -> int:
    ap = argparse.ArgumentParser(description="Fix recipe images in Supabase.")
    ap.add_argument("--apply", action="store_true", help="write changes (otherwise dry-run)")
    ap.add_argument("--dry-run", action="store_true", help="preview only (default)")
    ap.add_argument("--mealdb", action="store_true", help="also query TheMealDB for real per-dish photos (slower)")
    ap.add_argument("--force", action="store_true", help="overwrite even existing real photos")
    ap.add_argument("--limit", type=int, default=0, help="only process the first N recipes (testing)")
    args = ap.parse_args()
    apply = args.apply and not args.dry_run

    print("Loading recipes from Supabase…")
    res = supabase_admin.table("recipes").select("id, name, image_url").order("id").execute()
    recipes = res.data or []
    if args.limit:
        recipes = recipes[: args.limit]
    print(f"  {len(recipes)} recipes. Mode: {'APPLY' if apply else 'DRY-RUN'}"
          f"{' +mealdb' if args.mealdb else ''}{' +force' if args.force else ''}\n")

    client = httpx.Client() if args.mealdb else None
    updates: list[dict] = []
    changed = 0
    for r in recipes:
        new_url = resolve_image(r, use_mealdb=args.mealdb, force=args.force, client=client)
        if new_url and new_url != (r.get("image_url") or ""):
            changed += 1
            updates.append({"id": r["id"], "image_url": new_url})
            if changed <= 40 or changed % 50 == 0:
                print(f"  [{changed:4}] {str(r.get('name'))[:34]:34} → {new_url.split('/')[-1][:42]}")
        if args.mealdb:
            time.sleep(0.2)  # be polite to TheMealDB
    if client:
        client.close()

    print(f"\n{changed} of {len(recipes)} recipes would change.")
    if not apply:
        print("Dry-run — nothing written. Re-run with --apply to save.")
        return 0

    print("Writing updates to Supabase (batched)…")
    for i in range(0, len(updates), 100):
        batch = updates[i : i + 100]
        supabase_admin.table("recipes").upsert(batch, on_conflict="id").execute()
        print(f"  wrote {min(i + 100, len(updates))}/{len(updates)}")
    print("Done. The app trusts these images.unsplash.com URLs immediately.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
