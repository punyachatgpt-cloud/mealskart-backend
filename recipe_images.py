"""
Automatic recipe image resolution — the single source of truth for recipe photos.

Used at serve time (db._row_to_dict) so EVERY recipe — existing and any you add
later — always gets a correct, topical image with no manual steps. Also reused by
scripts/fix_recipe_images.py to clean the stored image_url column.

Resolution order for a recipe (name, image_url):
  1. If image_url is already one of our curated Unsplash images → keep it.
  2. If the dish name matches a curated category → a deterministic image from that
     category's pool (varied: different dishes in a category get different images).
  3. If it has some other real photo (a genuine foreign/MealDB dish) → keep it.
  4. Otherwise a generic food image.

This is fast (no network) so it's safe to run for every recipe on load.
"""
from __future__ import annotations

import hashlib

# ── Curated category image pools (Unsplash photo ids) ────────────────────────
CATEGORY_POOLS: dict[str, list[str]] = {
    "potato":   ["photo-1631515243349-e0cb75fb8d3a", "photo-1518977676601-b53f82aba655", "photo-1552332386-f8dd00dc2f85"],
    "paneer":   ["photo-1567188040759-fb8a883dc6d8", "photo-1601050690597-df0568f70950", "photo-1631452180519-c014fe946bc7"],
    "dal":      ["photo-1585937421612-70a008356fbe", "photo-1546833999-b9f581a1996d", "photo-1564894809611-1742fc40ed80"],
    "curry":    ["photo-1604908176997-125f25cc6f3d", "photo-1631292784640-2b24be784d5d", "photo-1455619452474-d2be8b1e70cd"],
    "biryani":  ["photo-1563379091339-03b21ab4a4f8", "photo-1589302168068-964664d93dc0", "photo-1633945274405-b6c8069047b0"],
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

# Keyword (whole word in dish name) → category.
KEYWORD_CATEGORY: dict[str, str] = {}
def _kw(cat: str, *words: str) -> None:
    for w in words:
        KEYWORD_CATEGORY[w] = cat

_kw("potato", "aloo", "potato", "gobi", "cauliflower", "palak", "spinach", "bhindi", "okra",
    "mushroom", "sabji", "sabzi", "bhaji", "vegetable", "veg", "baingan", "brinjal", "tinda", "lauki")
_kw("paneer", "paneer", "tofu")
_kw("dal", "dal", "daal", "lentil", "chana", "chickpea", "rajma", "moong", "sambar", "kadhi", "chole")
_kw("curry", "curry", "masala", "makhani", "korma", "kofta", "matar", "keema", "gravy", "saag", "rogan", "jalfrezi")
_kw("biryani", "biryani", "pulao", "pulav", "tehri")
_kw("rice", "rice", "khichdi", "khichuri", "pongal", "chawal")
_kw("bread", "roti", "chapati", "naan", "paratha", "puri", "poori", "kulcha", "bhatura", "thepla", "phulka")
_kw("southidli", "idli", "dosa", "uttapam", "upma", "poha", "vada", "appam", "pesarattu")
_kw("chicken", "chicken", "mutton", "lamb", "beef", "pork", "kebab", "tikka", "tandoori", "murgh", "seekh")
_kw("seafood", "fish", "prawn", "prawns", "shrimp", "crab", "machli", "macher", "pomfret")
_kw("egg", "egg", "omelette", "omelet", "anda", "bhurji")
_kw("soup", "soup", "broth", "rasam", "shorba")
_kw("salad", "salad", "raita", "sprouts", "kachumber", "kosambari")
_kw("drink", "lassi", "smoothie", "juice", "shake", "chai", "tea", "coffee", "sharbat", "thandai", "chaas", "buttermilk")
_kw("dessert", "halwa", "kheer", "payasam", "ladoo", "laddoo", "barfi", "gulab", "jamun",
    "jalebi", "rasgulla", "rasmalai", "gajar", "peda", "sandesh", "modak", "mithai", "kulfi",
    "sheer", "phirni", "sweet", "cake", "pudding", "custard", "shrikhand")
_kw("noodles", "noodle", "noodles", "ramen", "chowmein", "hakka", "schezwan", "maggi")
_kw("pasta", "pasta", "spaghetti", "penne", "lasagna", "lasagne", "macaroni")
_kw("snack", "samosa", "pakora", "pakoda", "chaat", "tikki", "cutlet", "roll", "sandwich",
    "frankie", "kachori", "bhel", "sev", "dhokla", "vada", "momo", "spring")

GENERIC_POOL = [
    "photo-1546069901-ba9599a7e63c", "photo-1565299624946-b28f40a0ae38",
    "photo-1504674900247-0877df9cc836", "photo-1565958011703-44f9829ba187",
]


def _unsplash(pid: str, w: int = 900) -> str:
    return f"https://images.unsplash.com/{pid}?auto=format&fit=crop&w={w}&q=82"


def category_for(name: str) -> str | None:
    words = "".join(c if (c.isalpha() or c.isspace()) else " " for c in (name or "").lower()).split()
    for word in words:
        if word in KEYWORD_CATEGORY:
            return KEYWORD_CATEGORY[word]
    return None


def _pick(pool: list[str], key: str) -> str:
    h = int(hashlib.md5(key.encode("utf-8")).hexdigest(), 16)
    return pool[h % len(pool)]


def resolve_image(name: str, image_url: str | None, recipe_id=None, w: int = 900) -> str:
    """Return the best image URL for a recipe — see module docstring for order."""
    url = image_url or ""
    if "images.unsplash.com" in url:
        return url
    cat = category_for(name)
    if cat and cat in CATEGORY_POOLS:
        return _unsplash(_pick(CATEGORY_POOLS[cat], f"{recipe_id}|{name}"), w)
    if url.startswith("http"):
        return url
    return _unsplash(_pick(GENERIC_POOL, name or str(recipe_id)), w)
