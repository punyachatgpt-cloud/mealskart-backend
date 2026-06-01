import asyncio
import csv
import os
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import httpx

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

import db as _db
from auth.dependencies import get_current_user, get_optional_user
from auth.router import router as auth_router
from auth.supabase_client import supabase_admin

load_dotenv()

_GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
print(f"[Gemini] Active model: {_GEMINI_MODEL}")

app = FastAPI(title="Recipe Recommender API")

# ── CORS ──────────────────────────────────────────────────────────────────────
# Allow the Vercel frontend origin(s) to call auth endpoints.
# Recipe routes were previously accessible from any origin (no CORS header set),
# which is preserved — CORSMiddleware only adds headers, never blocks.
_raw_origins = os.getenv("ALLOWED_ORIGINS", "")
_allow_origins = [o.strip() for o in _raw_origins.split(",") if o.strip()] or ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allow_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

# ── Auth routes ───────────────────────────────────────────────────────────────
# Mounted at /auth/* — all new files, no existing routes changed.
app.include_router(auth_router)


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
    # ── IDs 4–9, 11–30, 32–60 ────────────────────────────────────────────────
    4: {
        "servings": 1,
        "nutrition": {"protein_g": 5, "carbs_g": 40, "fat_g": 6, "fiber_g": 2},
        "ingredients_with_quantities": [
            {"name": "cooked rice", "quantity": 1, "unit": "cup"},
            {"name": "lemon juice", "quantity": 2, "unit": "tbsp"},
            {"name": "mustard seeds", "quantity": 0.5, "unit": "tsp"},
            {"name": "curry leaves", "quantity": 6, "unit": "leaves"},
            {"name": "peanuts", "quantity": 2, "unit": "tbsp"},
            {"name": "turmeric", "quantity": 0.25, "unit": "tsp"},
            {"name": "oil", "quantity": 1, "unit": "tsp"},
        ],
        "substitutions": {
            "lemon juice": ["amchur", "lime juice"],
            "peanuts": ["roasted chana", "cashews"],
        },
    },
    5: {
        "servings": 1,
        "nutrition": {"protein_g": 6, "carbs_g": 36, "fat_g": 7, "fiber_g": 4},
        "ingredients_with_quantities": [
            {"name": "semolina (rava)", "quantity": 0.5, "unit": "cup"},
            {"name": "mixed vegetables", "quantity": 0.5, "unit": "cup"},
            {"name": "onion", "quantity": 0.25, "unit": "cup"},
            {"name": "mustard seeds", "quantity": 0.5, "unit": "tsp"},
            {"name": "cashews", "quantity": 6, "unit": "pieces"},
            {"name": "oil", "quantity": 1.5, "unit": "tsp"},
        ],
        "substitutions": {
            "semolina (rava)": ["oats", "cornmeal"],
            "cashews": ["peanuts", "almonds"],
        },
    },
    6: {
        "servings": 1,
        "nutrition": {"protein_g": 9, "carbs_g": 32, "fat_g": 6, "fiber_g": 5},
        "ingredients_with_quantities": [
            {"name": "rolled oats", "quantity": 0.5, "unit": "cup"},
            {"name": "onion", "quantity": 0.25, "unit": "cup"},
            {"name": "tomato", "quantity": 0.25, "unit": "cup"},
            {"name": "green chili", "quantity": 1, "unit": "piece"},
            {"name": "mustard seeds", "quantity": 0.5, "unit": "tsp"},
            {"name": "oil", "quantity": 1, "unit": "tsp"},
        ],
        "substitutions": {
            "rolled oats": ["quick oats", "daliya"],
            "green chili": ["black pepper", "red chili flakes"],
        },
    },
    7: {
        "servings": 1,
        "nutrition": {"protein_g": 14, "carbs_g": 28, "fat_g": 6, "fiber_g": 7},
        "ingredients_with_quantities": [
            {"name": "moong dal", "quantity": 0.5, "unit": "cup"},
            {"name": "onion", "quantity": 0.25, "unit": "cup"},
            {"name": "tomato", "quantity": 0.25, "unit": "cup"},
            {"name": "garlic", "quantity": 2, "unit": "cloves"},
            {"name": "cumin seeds", "quantity": 0.5, "unit": "tsp"},
            {"name": "turmeric", "quantity": 0.25, "unit": "tsp"},
            {"name": "oil", "quantity": 1, "unit": "tsp"},
        ],
        "substitutions": {
            "moong dal": ["masoor dal", "chana dal"],
            "garlic": ["ginger-garlic paste", "asafoetida"],
        },
    },
    8: {
        "servings": 1,
        "nutrition": {"protein_g": 5, "carbs_g": 22, "fat_g": 7, "fiber_g": 5},
        "ingredients_with_quantities": [
            {"name": "spinach", "quantity": 1, "unit": "cup"},
            {"name": "sweet corn", "quantity": 0.5, "unit": "cup"},
            {"name": "onion", "quantity": 0.25, "unit": "cup"},
            {"name": "garlic", "quantity": 2, "unit": "cloves"},
            {"name": "oil", "quantity": 1, "unit": "tsp"},
        ],
        "substitutions": {
            "sweet corn": ["peas", "chickpeas"],
            "spinach": ["kale", "methi leaves"],
        },
    },
    9: {
        "servings": 1,
        "nutrition": {"protein_g": 4, "carbs_g": 34, "fat_g": 8, "fiber_g": 4},
        "ingredients_with_quantities": [
            {"name": "potato", "quantity": 2, "unit": "medium"},
            {"name": "cumin seeds", "quantity": 0.5, "unit": "tsp"},
            {"name": "coriander powder", "quantity": 0.5, "unit": "tsp"},
            {"name": "turmeric", "quantity": 0.25, "unit": "tsp"},
            {"name": "amchur", "quantity": 0.5, "unit": "tsp"},
            {"name": "oil", "quantity": 1.5, "unit": "tsp"},
        ],
        "substitutions": {
            "potato": ["sweet potato", "yam"],
            "amchur": ["lemon juice", "tamarind paste"],
        },
    },
    11: {
        "servings": 1,
        "nutrition": {"protein_g": 20, "carbs_g": 8, "fat_g": 16, "fiber_g": 2},
        "ingredients_with_quantities": [
            {"name": "paneer", "quantity": 150, "unit": "g"},
            {"name": "yogurt", "quantity": 3, "unit": "tbsp"},
            {"name": "ginger-garlic paste", "quantity": 1, "unit": "tsp"},
            {"name": "tikka masala", "quantity": 1, "unit": "tsp"},
            {"name": "lemon juice", "quantity": 1, "unit": "tbsp"},
            {"name": "oil", "quantity": 1, "unit": "tsp"},
        ],
        "substitutions": {
            "paneer": ["tofu", "halloumi"],
            "yogurt": ["thick curd", "plant yogurt"],
        },
    },
    12: {
        "servings": 1,
        "nutrition": {"protein_g": 7, "carbs_g": 46, "fat_g": 8, "fiber_g": 4},
        "ingredients_with_quantities": [
            {"name": "basmati rice", "quantity": 0.5, "unit": "cup"},
            {"name": "mixed vegetables", "quantity": 0.5, "unit": "cup"},
            {"name": "onion", "quantity": 0.25, "unit": "cup"},
            {"name": "whole spices", "quantity": 1, "unit": "tsp"},
            {"name": "ghee", "quantity": 1, "unit": "tsp"},
        ],
        "substitutions": {
            "basmati rice": ["brown rice", "jeera rice"],
            "ghee": ["oil", "butter"],
        },
    },
    13: {
        "servings": 1,
        "nutrition": {"protein_g": 12, "carbs_g": 30, "fat_g": 4, "fiber_g": 9},
        "ingredients_with_quantities": [
            {"name": "chickpeas (boiled)", "quantity": 0.75, "unit": "cup"},
            {"name": "onion", "quantity": 0.25, "unit": "cup"},
            {"name": "tomato", "quantity": 0.25, "unit": "cup"},
            {"name": "tamarind chutney", "quantity": 1, "unit": "tbsp"},
            {"name": "chaat masala", "quantity": 0.5, "unit": "tsp"},
            {"name": "coriander", "quantity": 2, "unit": "tbsp"},
        ],
        "substitutions": {
            "chickpeas (boiled)": ["black chickpeas", "kidney beans"],
            "tamarind chutney": ["lemon juice + jaggery", "raw mango"],
        },
    },
    14: {
        "servings": 1,
        "nutrition": {"protein_g": 4, "carbs_g": 28, "fat_g": 7, "fiber_g": 5},
        "ingredients_with_quantities": [
            {"name": "cauliflower", "quantity": 1, "unit": "cup"},
            {"name": "potato", "quantity": 1, "unit": "medium"},
            {"name": "onion", "quantity": 0.25, "unit": "cup"},
            {"name": "tomato", "quantity": 0.25, "unit": "cup"},
            {"name": "turmeric", "quantity": 0.25, "unit": "tsp"},
            {"name": "oil", "quantity": 1.5, "unit": "tsp"},
        ],
        "substitutions": {
            "cauliflower": ["broccoli", "cabbage"],
            "potato": ["sweet potato", "yam"],
        },
    },
    15: {
        "servings": 1,
        "nutrition": {"protein_g": 3, "carbs_g": 14, "fat_g": 5, "fiber_g": 3},
        "ingredients_with_quantities": [
            {"name": "tomatoes", "quantity": 3, "unit": "medium"},
            {"name": "onion", "quantity": 0.25, "unit": "cup"},
            {"name": "garlic", "quantity": 2, "unit": "cloves"},
            {"name": "ginger", "quantity": 0.5, "unit": "tsp"},
            {"name": "cream", "quantity": 1, "unit": "tbsp"},
            {"name": "oil", "quantity": 1, "unit": "tsp"},
        ],
        "substitutions": {
            "cream": ["coconut milk", "cashew paste"],
            "tomatoes": ["canned tomatoes", "tomato puree"],
        },
    },
    16: {
        "servings": 1,
        "nutrition": {"protein_g": 8, "carbs_g": 48, "fat_g": 9, "fiber_g": 3},
        "ingredients_with_quantities": [
            {"name": "cooked rice", "quantity": 1, "unit": "cup"},
            {"name": "mixed vegetables", "quantity": 0.5, "unit": "cup"},
            {"name": "egg", "quantity": 1, "unit": "piece"},
            {"name": "soy sauce", "quantity": 1, "unit": "tbsp"},
            {"name": "garlic", "quantity": 2, "unit": "cloves"},
            {"name": "oil", "quantity": 1.5, "unit": "tsp"},
        ],
        "substitutions": {
            "egg": ["tofu scramble", "paneer crumbles"],
            "soy sauce": ["coconut aminos", "tamari"],
        },
    },
    17: {
        "servings": 1,
        "nutrition": {"protein_g": 10, "carbs_g": 20, "fat_g": 3, "fiber_g": 7},
        "ingredients_with_quantities": [
            {"name": "mixed sprouts", "quantity": 1, "unit": "cup"},
            {"name": "onion", "quantity": 0.25, "unit": "cup"},
            {"name": "tomato", "quantity": 0.25, "unit": "cup"},
            {"name": "cucumber", "quantity": 0.25, "unit": "cup"},
            {"name": "lemon juice", "quantity": 1, "unit": "tbsp"},
            {"name": "chaat masala", "quantity": 0.25, "unit": "tsp"},
        ],
        "substitutions": {
            "mixed sprouts": ["moong sprouts", "chickpea sprouts"],
            "lemon juice": ["lime juice", "amchur"],
        },
    },
    18: {
        "servings": 1,
        "nutrition": {"protein_g": 9, "carbs_g": 36, "fat_g": 8, "fiber_g": 3},
        "ingredients_with_quantities": [
            {"name": "bread slices", "quantity": 2, "unit": "slices"},
            {"name": "paneer or cheese", "quantity": 50, "unit": "g"},
            {"name": "mixed vegetables", "quantity": 0.5, "unit": "cup"},
            {"name": "green chutney", "quantity": 1, "unit": "tbsp"},
            {"name": "butter", "quantity": 1, "unit": "tsp"},
        ],
        "substitutions": {
            "bread slices": ["whole wheat bread", "multigrain bread"],
            "paneer or cheese": ["tofu", "hummus"],
        },
    },
    19: {
        "servings": 1,
        "nutrition": {"protein_g": 5, "carbs_g": 12, "fat_g": 8, "fiber_g": 3},
        "ingredients_with_quantities": [
            {"name": "mushrooms", "quantity": 1.5, "unit": "cups"},
            {"name": "garlic", "quantity": 4, "unit": "cloves"},
            {"name": "butter", "quantity": 1, "unit": "tbsp"},
            {"name": "soy sauce", "quantity": 1, "unit": "tsp"},
            {"name": "black pepper", "quantity": 0.5, "unit": "tsp"},
        ],
        "substitutions": {
            "mushrooms": ["zucchini", "broccoli"],
            "butter": ["olive oil", "ghee"],
        },
    },
    20: {
        "servings": 1,
        "nutrition": {"protein_g": 3, "carbs_g": 14, "fat_g": 7, "fiber_g": 5},
        "ingredients_with_quantities": [
            {"name": "okra (bhindi)", "quantity": 200, "unit": "g"},
            {"name": "onion", "quantity": 0.25, "unit": "cup"},
            {"name": "cumin seeds", "quantity": 0.5, "unit": "tsp"},
            {"name": "coriander powder", "quantity": 0.5, "unit": "tsp"},
            {"name": "amchur", "quantity": 0.25, "unit": "tsp"},
            {"name": "oil", "quantity": 1.5, "unit": "tsp"},
        ],
        "substitutions": {
            "okra (bhindi)": ["baby corn", "green beans"],
            "amchur": ["lemon juice", "tamarind"],
        },
    },
    21: {
        "servings": 1,
        "nutrition": {"protein_g": 12, "carbs_g": 42, "fat_g": 6, "fiber_g": 8},
        "ingredients_with_quantities": [
            {"name": "moong dal", "quantity": 0.25, "unit": "cup"},
            {"name": "rice", "quantity": 0.25, "unit": "cup"},
            {"name": "turmeric", "quantity": 0.25, "unit": "tsp"},
            {"name": "cumin seeds", "quantity": 0.5, "unit": "tsp"},
            {"name": "ghee", "quantity": 1, "unit": "tsp"},
        ],
        "substitutions": {
            "moong dal": ["masoor dal", "toor dal"],
            "ghee": ["oil", "butter"],
        },
    },
    22: {
        "servings": 1,
        "nutrition": {"protein_g": 9, "carbs_g": 30, "fat_g": 12, "fiber_g": 3},
        "ingredients_with_quantities": [
            {"name": "curd", "quantity": 1, "unit": "cup"},
            {"name": "besan", "quantity": 3, "unit": "tbsp"},
            {"name": "onion", "quantity": 0.25, "unit": "cup"},
            {"name": "mustard seeds", "quantity": 0.5, "unit": "tsp"},
            {"name": "dried red chili", "quantity": 1, "unit": "piece"},
            {"name": "oil", "quantity": 1.5, "unit": "tsp"},
        ],
        "substitutions": {
            "curd": ["plant yogurt", "thick buttermilk"],
            "besan": ["oats flour", "rice flour"],
        },
    },
    23: {
        "servings": 1,
        "nutrition": {"protein_g": 18, "carbs_g": 16, "fat_g": 20, "fiber_g": 2},
        "ingredients_with_quantities": [
            {"name": "paneer", "quantity": 100, "unit": "g"},
            {"name": "butter", "quantity": 1, "unit": "tbsp"},
            {"name": "tomato puree", "quantity": 0.5, "unit": "cup"},
            {"name": "cream", "quantity": 2, "unit": "tbsp"},
            {"name": "ginger-garlic paste", "quantity": 1, "unit": "tsp"},
            {"name": "kashmiri chili powder", "quantity": 0.5, "unit": "tsp"},
        ],
        "substitutions": {
            "paneer": ["tofu", "mushrooms"],
            "cream": ["coconut cream", "cashew paste"],
        },
    },
    24: {
        "servings": 1,
        "nutrition": {"protein_g": 22, "carbs_g": 18, "fat_g": 9, "fiber_g": 6},
        "ingredients_with_quantities": [
            {"name": "soya chunks", "quantity": 0.75, "unit": "cup"},
            {"name": "onion", "quantity": 0.25, "unit": "cup"},
            {"name": "tomato", "quantity": 0.25, "unit": "cup"},
            {"name": "ginger-garlic paste", "quantity": 1, "unit": "tsp"},
            {"name": "garam masala", "quantity": 0.5, "unit": "tsp"},
            {"name": "oil", "quantity": 1, "unit": "tsp"},
        ],
        "substitutions": {
            "soya chunks": ["chickpeas", "paneer"],
            "garam masala": ["curry powder", "kitchen king masala"],
        },
    },
    25: {
        "servings": 1,
        "nutrition": {"protein_g": 8, "carbs_g": 52, "fat_g": 10, "fiber_g": 4},
        "ingredients_with_quantities": [
            {"name": "noodles (hakka)", "quantity": 75, "unit": "g"},
            {"name": "mixed vegetables", "quantity": 0.75, "unit": "cup"},
            {"name": "soy sauce", "quantity": 1.5, "unit": "tbsp"},
            {"name": "garlic", "quantity": 3, "unit": "cloves"},
            {"name": "oil", "quantity": 1.5, "unit": "tsp"},
        ],
        "substitutions": {
            "noodles (hakka)": ["rice noodles", "whole wheat noodles"],
            "soy sauce": ["coconut aminos", "tamari"],
        },
    },
    26: {
        "servings": 1,
        "nutrition": {"protein_g": 14, "carbs_g": 6, "fat_g": 12, "fiber_g": 1},
        "ingredients_with_quantities": [
            {"name": "eggs", "quantity": 3, "unit": "pieces"},
            {"name": "onion", "quantity": 0.25, "unit": "cup"},
            {"name": "tomato", "quantity": 0.25, "unit": "cup"},
            {"name": "green chili", "quantity": 1, "unit": "piece"},
            {"name": "coriander", "quantity": 2, "unit": "tbsp"},
            {"name": "oil", "quantity": 1, "unit": "tsp"},
        ],
        "substitutions": {
            "eggs": ["tofu scramble", "paneer crumbles"],
            "green chili": ["black pepper", "red chili flakes"],
        },
    },
    27: {
        "servings": 1,
        "nutrition": {"protein_g": 12, "carbs_g": 12, "fat_g": 10, "fiber_g": 2},
        "ingredients_with_quantities": [
            {"name": "eggs", "quantity": 2, "unit": "pieces"},
            {"name": "onion", "quantity": 0.5, "unit": "cup"},
            {"name": "tomato", "quantity": 0.5, "unit": "cup"},
            {"name": "ginger-garlic paste", "quantity": 1, "unit": "tsp"},
            {"name": "turmeric", "quantity": 0.25, "unit": "tsp"},
            {"name": "oil", "quantity": 1.5, "unit": "tsp"},
        ],
        "substitutions": {
            "eggs": ["paneer", "tofu"],
        },
    },
    28: {
        "servings": 1,
        "nutrition": {"protein_g": 28, "carbs_g": 6, "fat_g": 12, "fiber_g": 1},
        "ingredients_with_quantities": [
            {"name": "chicken", "quantity": 150, "unit": "g"},
            {"name": "black pepper", "quantity": 1, "unit": "tsp"},
            {"name": "garlic", "quantity": 3, "unit": "cloves"},
            {"name": "lemon juice", "quantity": 1, "unit": "tbsp"},
            {"name": "oil", "quantity": 1.5, "unit": "tsp"},
        ],
        "substitutions": {
            "chicken": ["paneer", "fish fillet"],
            "black pepper": ["white pepper", "pepper powder blend"],
        },
    },
    29: {
        "servings": 1,
        "nutrition": {"protein_g": 26, "carbs_g": 10, "fat_g": 10, "fiber_g": 3},
        "ingredients_with_quantities": [
            {"name": "chicken", "quantity": 150, "unit": "g"},
            {"name": "mixed vegetables", "quantity": 0.5, "unit": "cup"},
            {"name": "soy sauce", "quantity": 1, "unit": "tbsp"},
            {"name": "garlic", "quantity": 3, "unit": "cloves"},
            {"name": "ginger", "quantity": 1, "unit": "tsp"},
            {"name": "oil", "quantity": 1.5, "unit": "tsp"},
        ],
        "substitutions": {
            "chicken": ["prawns", "paneer"],
            "soy sauce": ["oyster sauce", "coconut aminos"],
        },
    },
    30: {
        "servings": 1,
        "nutrition": {"protein_g": 24, "carbs_g": 16, "fat_g": 14, "fiber_g": 5},
        "ingredients_with_quantities": [
            {"name": "minced mutton", "quantity": 150, "unit": "g"},
            {"name": "peas", "quantity": 0.5, "unit": "cup"},
            {"name": "onion", "quantity": 0.5, "unit": "cup"},
            {"name": "tomato", "quantity": 0.25, "unit": "cup"},
            {"name": "ginger-garlic paste", "quantity": 1, "unit": "tsp"},
            {"name": "garam masala", "quantity": 0.5, "unit": "tsp"},
            {"name": "oil", "quantity": 1.5, "unit": "tsp"},
        ],
        "substitutions": {
            "minced mutton": ["minced chicken", "soya mince"],
            "peas": ["corn", "edamame"],
        },
    },
    32: {
        "servings": 1,
        "nutrition": {"protein_g": 22, "carbs_g": 6, "fat_g": 10, "fiber_g": 1},
        "ingredients_with_quantities": [
            {"name": "prawns", "quantity": 150, "unit": "g"},
            {"name": "garlic", "quantity": 3, "unit": "cloves"},
            {"name": "lemon juice", "quantity": 1, "unit": "tbsp"},
            {"name": "red chili powder", "quantity": 0.5, "unit": "tsp"},
            {"name": "oil", "quantity": 1.5, "unit": "tsp"},
        ],
        "substitutions": {
            "prawns": ["fish fillet", "calamari"],
            "lemon juice": ["lime juice", "amchur"],
        },
    },
    33: {
        "servings": 1,
        "nutrition": {"protein_g": 14, "carbs_g": 46, "fat_g": 10, "fiber_g": 2},
        "ingredients_with_quantities": [
            {"name": "cooked rice", "quantity": 1, "unit": "cup"},
            {"name": "eggs", "quantity": 2, "unit": "pieces"},
            {"name": "mixed vegetables", "quantity": 0.5, "unit": "cup"},
            {"name": "soy sauce", "quantity": 1, "unit": "tbsp"},
            {"name": "garlic", "quantity": 2, "unit": "cloves"},
            {"name": "oil", "quantity": 1.5, "unit": "tsp"},
        ],
        "substitutions": {
            "eggs": ["tofu scramble", "paneer"],
            "soy sauce": ["coconut aminos", "tamari"],
        },
    },
    34: {
        "servings": 1,
        "nutrition": {"protein_g": 20, "carbs_g": 22, "fat_g": 10, "fiber_g": 2},
        "ingredients_with_quantities": [
            {"name": "chicken mince", "quantity": 100, "unit": "g"},
            {"name": "semolina (rava)", "quantity": 3, "unit": "tbsp"},
            {"name": "onion", "quantity": 0.25, "unit": "cup"},
            {"name": "egg", "quantity": 1, "unit": "piece"},
            {"name": "spices", "quantity": 1, "unit": "tsp"},
            {"name": "oil", "quantity": 1, "unit": "tsp"},
        ],
        "substitutions": {
            "chicken mince": ["paneer crumbles", "fish mince"],
            "semolina (rava)": ["breadcrumbs", "oats"],
        },
    },
    35: {
        "servings": 1,
        "nutrition": {"protein_g": 24, "carbs_g": 10, "fat_g": 12, "fiber_g": 2},
        "ingredients_with_quantities": [
            {"name": "fish fillet", "quantity": 150, "unit": "g"},
            {"name": "onion", "quantity": 0.5, "unit": "cup"},
            {"name": "tomato", "quantity": 0.5, "unit": "cup"},
            {"name": "coconut milk", "quantity": 3, "unit": "tbsp"},
            {"name": "ginger-garlic paste", "quantity": 1, "unit": "tsp"},
            {"name": "oil", "quantity": 1.5, "unit": "tsp"},
        ],
        "substitutions": {
            "fish fillet": ["prawns", "tofu"],
            "coconut milk": ["curd", "cashew paste"],
        },
    },
    36: {
        "servings": 1,
        "nutrition": {"protein_g": 28, "carbs_g": 6, "fat_g": 10, "fiber_g": 1},
        "ingredients_with_quantities": [
            {"name": "chicken", "quantity": 150, "unit": "g"},
            {"name": "yogurt", "quantity": 3, "unit": "tbsp"},
            {"name": "tikka masala", "quantity": 1.5, "unit": "tsp"},
            {"name": "lemon juice", "quantity": 1, "unit": "tbsp"},
            {"name": "ginger-garlic paste", "quantity": 1, "unit": "tsp"},
            {"name": "oil", "quantity": 1, "unit": "tsp"},
        ],
        "substitutions": {
            "chicken": ["paneer", "fish fillet"],
            "yogurt": ["thick curd", "plant yogurt"],
        },
    },
    37: {
        "servings": 1,
        "nutrition": {"protein_g": 28, "carbs_g": 4, "fat_g": 10, "fiber_g": 1},
        "ingredients_with_quantities": [
            {"name": "chicken", "quantity": 150, "unit": "g"},
            {"name": "lemon juice", "quantity": 2, "unit": "tbsp"},
            {"name": "black pepper", "quantity": 1, "unit": "tsp"},
            {"name": "garlic", "quantity": 3, "unit": "cloves"},
            {"name": "butter", "quantity": 0.5, "unit": "tbsp"},
        ],
        "substitutions": {
            "chicken": ["fish fillet", "paneer"],
            "butter": ["olive oil", "ghee"],
        },
    },
    38: {
        "servings": 1,
        "nutrition": {"protein_g": 14, "carbs_g": 8, "fat_g": 12, "fiber_g": 2},
        "ingredients_with_quantities": [
            {"name": "eggs", "quantity": 3, "unit": "pieces"},
            {"name": "onion", "quantity": 0.25, "unit": "cup"},
            {"name": "tomato", "quantity": 0.25, "unit": "cup"},
            {"name": "green chili", "quantity": 1, "unit": "piece"},
            {"name": "cumin seeds", "quantity": 0.25, "unit": "tsp"},
            {"name": "oil", "quantity": 1, "unit": "tsp"},
        ],
        "substitutions": {
            "eggs": ["egg whites", "tofu scramble"],
            "green chili": ["jalapeño", "black pepper"],
        },
    },
    39: {
        "servings": 1,
        "nutrition": {"protein_g": 22, "carbs_g": 34, "fat_g": 12, "fiber_g": 3},
        "ingredients_with_quantities": [
            {"name": "chicken tikka", "quantity": 100, "unit": "g"},
            {"name": "roti / paratha", "quantity": 1, "unit": "piece"},
            {"name": "onion", "quantity": 0.25, "unit": "cup"},
            {"name": "green chutney", "quantity": 1, "unit": "tbsp"},
            {"name": "lemon juice", "quantity": 1, "unit": "tsp"},
        ],
        "substitutions": {
            "chicken tikka": ["paneer tikka", "egg bhurji"],
            "roti / paratha": ["whole wheat tortilla", "rumali roti"],
        },
    },
    40: {
        "servings": 1,
        "nutrition": {"protein_g": 26, "carbs_g": 12, "fat_g": 18, "fiber_g": 3},
        "ingredients_with_quantities": [
            {"name": "mutton mince", "quantity": 150, "unit": "g"},
            {"name": "onion", "quantity": 0.5, "unit": "cup"},
            {"name": "tomato", "quantity": 0.25, "unit": "cup"},
            {"name": "ginger-garlic paste", "quantity": 1, "unit": "tsp"},
            {"name": "garam masala", "quantity": 0.5, "unit": "tsp"},
            {"name": "oil", "quantity": 2, "unit": "tsp"},
        ],
        "substitutions": {
            "mutton mince": ["chicken mince", "soya mince"],
        },
    },
    41: {
        "servings": 1,
        "nutrition": {"protein_g": 24, "carbs_g": 12, "fat_g": 16, "fiber_g": 2},
        "ingredients_with_quantities": [
            {"name": "chicken", "quantity": 150, "unit": "g"},
            {"name": "coconut milk", "quantity": 0.5, "unit": "cup"},
            {"name": "onion", "quantity": 0.5, "unit": "cup"},
            {"name": "tomato", "quantity": 0.25, "unit": "cup"},
            {"name": "ginger-garlic paste", "quantity": 1, "unit": "tsp"},
            {"name": "oil", "quantity": 1.5, "unit": "tsp"},
        ],
        "substitutions": {
            "coconut milk": ["cashew cream", "curd"],
            "chicken": ["prawns", "tofu"],
        },
    },
    42: {
        "servings": 1,
        "nutrition": {"protein_g": 26, "carbs_g": 10, "fat_g": 12, "fiber_g": 4},
        "ingredients_with_quantities": [
            {"name": "chicken", "quantity": 150, "unit": "g"},
            {"name": "spinach", "quantity": 1.5, "unit": "cups"},
            {"name": "onion", "quantity": 0.5, "unit": "cup"},
            {"name": "ginger-garlic paste", "quantity": 1, "unit": "tsp"},
            {"name": "oil", "quantity": 1.5, "unit": "tsp"},
        ],
        "substitutions": {
            "spinach": ["methi", "kale"],
            "chicken": ["paneer", "prawns"],
        },
    },
    43: {
        "servings": 1,
        "nutrition": {"protein_g": 12, "carbs_g": 14, "fat_g": 10, "fiber_g": 2},
        "ingredients_with_quantities": [
            {"name": "eggs", "quantity": 2, "unit": "pieces"},
            {"name": "onion", "quantity": 0.5, "unit": "cup"},
            {"name": "tomato", "quantity": 0.5, "unit": "cup"},
            {"name": "coconut", "quantity": 2, "unit": "tbsp"},
            {"name": "curry leaves", "quantity": 8, "unit": "leaves"},
            {"name": "oil", "quantity": 1.5, "unit": "tsp"},
        ],
        "substitutions": {
            "eggs": ["paneer", "tofu"],
            "coconut": ["coconut milk", "desiccated coconut"],
        },
    },
    44: {
        "servings": 1,
        "nutrition": {"protein_g": 18, "carbs_g": 14, "fat_g": 6, "fiber_g": 4},
        "ingredients_with_quantities": [
            {"name": "chicken", "quantity": 100, "unit": "g"},
            {"name": "mixed vegetables", "quantity": 0.75, "unit": "cup"},
            {"name": "onion", "quantity": 0.25, "unit": "cup"},
            {"name": "ginger", "quantity": 1, "unit": "tsp"},
            {"name": "black pepper", "quantity": 0.5, "unit": "tsp"},
        ],
        "substitutions": {
            "chicken": ["tofu", "paneer"],
        },
    },
    45: {
        "servings": 1,
        "nutrition": {"protein_g": 26, "carbs_g": 6, "fat_g": 12, "fiber_g": 1},
        "ingredients_with_quantities": [
            {"name": "fish fillet", "quantity": 150, "unit": "g"},
            {"name": "yogurt", "quantity": 3, "unit": "tbsp"},
            {"name": "tikka masala", "quantity": 1.5, "unit": "tsp"},
            {"name": "lemon juice", "quantity": 1, "unit": "tbsp"},
            {"name": "oil", "quantity": 1, "unit": "tsp"},
        ],
        "substitutions": {
            "fish fillet": ["prawns", "chicken"],
            "yogurt": ["thick curd", "plant yogurt"],
        },
    },
    46: {
        "servings": 1,
        "nutrition": {"protein_g": 20, "carbs_g": 48, "fat_g": 10, "fiber_g": 3},
        "ingredients_with_quantities": [
            {"name": "noodles", "quantity": 75, "unit": "g"},
            {"name": "chicken", "quantity": 100, "unit": "g"},
            {"name": "mixed vegetables", "quantity": 0.5, "unit": "cup"},
            {"name": "soy sauce", "quantity": 1, "unit": "tbsp"},
            {"name": "garlic", "quantity": 2, "unit": "cloves"},
            {"name": "oil", "quantity": 1.5, "unit": "tsp"},
        ],
        "substitutions": {
            "chicken": ["prawns", "tofu"],
            "noodles": ["rice noodles", "whole wheat noodles"],
        },
    },
    47: {
        "servings": 1,
        "nutrition": {"protein_g": 26, "carbs_g": 8, "fat_g": 10, "fiber_g": 2},
        "ingredients_with_quantities": [
            {"name": "chicken", "quantity": 150, "unit": "g"},
            {"name": "fresh basil", "quantity": 0.25, "unit": "cup"},
            {"name": "garlic", "quantity": 4, "unit": "cloves"},
            {"name": "soy sauce", "quantity": 1, "unit": "tbsp"},
            {"name": "oil", "quantity": 1.5, "unit": "tsp"},
        ],
        "substitutions": {
            "fresh basil": ["dried basil", "Thai basil"],
            "chicken": ["prawns", "tofu"],
        },
    },
    48: {
        "servings": 1,
        "nutrition": {"protein_g": 14, "carbs_g": 16, "fat_g": 12, "fiber_g": 4},
        "ingredients_with_quantities": [
            {"name": "eggs", "quantity": 2, "unit": "pieces"},
            {"name": "tomatoes", "quantity": 2, "unit": "medium"},
            {"name": "onion", "quantity": 0.5, "unit": "cup"},
            {"name": "bell pepper", "quantity": 0.5, "unit": "cup"},
            {"name": "cumin seeds", "quantity": 0.5, "unit": "tsp"},
            {"name": "oil", "quantity": 1.5, "unit": "tsp"},
        ],
        "substitutions": {
            "eggs": ["tofu", "paneer"],
            "bell pepper": ["capsicum", "zucchini"],
        },
    },
    49: {
        "servings": 1,
        "nutrition": {"protein_g": 24, "carbs_g": 14, "fat_g": 8, "fiber_g": 5},
        "ingredients_with_quantities": [
            {"name": "tuna (canned)", "quantity": 100, "unit": "g"},
            {"name": "mixed greens", "quantity": 1.5, "unit": "cups"},
            {"name": "cucumber", "quantity": 0.5, "unit": "cup"},
            {"name": "cherry tomatoes", "quantity": 0.5, "unit": "cup"},
            {"name": "lemon dressing", "quantity": 2, "unit": "tbsp"},
        ],
        "substitutions": {
            "tuna (canned)": ["boiled chicken", "boiled egg"],
            "mixed greens": ["spinach", "cabbage"],
        },
    },
    50: {
        "servings": 1,
        "nutrition": {"protein_g": 22, "carbs_g": 36, "fat_g": 12, "fiber_g": 3},
        "ingredients_with_quantities": [
            {"name": "chicken", "quantity": 100, "unit": "g"},
            {"name": "bread / bun", "quantity": 1, "unit": "piece"},
            {"name": "onion", "quantity": 0.25, "unit": "cup"},
            {"name": "tomato", "quantity": 0.25, "unit": "cup"},
            {"name": "masala paste", "quantity": 1, "unit": "tbsp"},
            {"name": "oil", "quantity": 1, "unit": "tsp"},
        ],
        "substitutions": {
            "chicken": ["paneer", "egg"],
            "bread / bun": ["whole wheat bun", "pita"],
        },
    },
    51: {
        "servings": 1,
        "nutrition": {"protein_g": 30, "carbs_g": 14, "fat_g": 22, "fiber_g": 2},
        "ingredients_with_quantities": [
            {"name": "chicken", "quantity": 200, "unit": "g"},
            {"name": "butter", "quantity": 1.5, "unit": "tbsp"},
            {"name": "tomato puree", "quantity": 0.5, "unit": "cup"},
            {"name": "cream", "quantity": 3, "unit": "tbsp"},
            {"name": "ginger-garlic paste", "quantity": 1.5, "unit": "tsp"},
            {"name": "kashmiri chili powder", "quantity": 1, "unit": "tsp"},
            {"name": "garam masala", "quantity": 0.5, "unit": "tsp"},
        ],
        "substitutions": {
            "cream": ["coconut cream", "cashew paste"],
            "chicken": ["paneer", "mushrooms"],
        },
    },
    52: {
        "servings": 1,
        "nutrition": {"protein_g": 14, "carbs_g": 32, "fat_g": 14, "fiber_g": 10},
        "ingredients_with_quantities": [
            {"name": "whole black lentils (urad)", "quantity": 0.5, "unit": "cup"},
            {"name": "kidney beans", "quantity": 0.25, "unit": "cup"},
            {"name": "butter", "quantity": 1.5, "unit": "tbsp"},
            {"name": "cream", "quantity": 2, "unit": "tbsp"},
            {"name": "tomato puree", "quantity": 0.5, "unit": "cup"},
            {"name": "ginger-garlic paste", "quantity": 1, "unit": "tsp"},
        ],
        "substitutions": {
            "cream": ["coconut cream", "cashew paste"],
            "butter": ["ghee", "oil"],
        },
    },
    53: {
        "servings": 1,
        "nutrition": {"protein_g": 28, "carbs_g": 12, "fat_g": 18, "fiber_g": 2},
        "ingredients_with_quantities": [
            {"name": "chicken tikka", "quantity": 200, "unit": "g"},
            {"name": "tomato puree", "quantity": 0.5, "unit": "cup"},
            {"name": "cream", "quantity": 2, "unit": "tbsp"},
            {"name": "onion", "quantity": 0.5, "unit": "cup"},
            {"name": "ginger-garlic paste", "quantity": 1.5, "unit": "tsp"},
            {"name": "garam masala", "quantity": 0.5, "unit": "tsp"},
            {"name": "oil", "quantity": 1.5, "unit": "tsp"},
        ],
        "substitutions": {
            "chicken tikka": ["paneer tikka", "tofu tikka"],
            "cream": ["coconut cream", "cashew paste"],
        },
    },
    54: {
        "servings": 1,
        "nutrition": {"protein_g": 16, "carbs_g": 12, "fat_g": 18, "fiber_g": 5},
        "ingredients_with_quantities": [
            {"name": "paneer", "quantity": 100, "unit": "g"},
            {"name": "spinach", "quantity": 2, "unit": "cups"},
            {"name": "onion", "quantity": 0.5, "unit": "cup"},
            {"name": "ginger-garlic paste", "quantity": 1, "unit": "tsp"},
            {"name": "cream", "quantity": 1, "unit": "tbsp"},
            {"name": "ghee", "quantity": 1, "unit": "tsp"},
        ],
        "substitutions": {
            "paneer": ["tofu", "chickpeas"],
            "cream": ["coconut cream", "cashew paste"],
        },
    },
    55: {
        "servings": 1,
        "nutrition": {"protein_g": 28, "carbs_g": 52, "fat_g": 14, "fiber_g": 3},
        "ingredients_with_quantities": [
            {"name": "chicken", "quantity": 200, "unit": "g"},
            {"name": "basmati rice", "quantity": 0.75, "unit": "cup"},
            {"name": "yogurt", "quantity": 0.25, "unit": "cup"},
            {"name": "whole spices", "quantity": 1.5, "unit": "tsp"},
            {"name": "saffron", "quantity": 1, "unit": "pinch"},
            {"name": "fried onions", "quantity": 3, "unit": "tbsp"},
            {"name": "ghee", "quantity": 1.5, "unit": "tsp"},
        ],
        "substitutions": {
            "chicken": ["mutton", "paneer"],
            "saffron": ["turmeric water", "food colour"],
        },
    },
    56: {
        "servings": 1,
        "nutrition": {"protein_g": 14, "carbs_g": 14, "fat_g": 20, "fiber_g": 2},
        "ingredients_with_quantities": [
            {"name": "paneer", "quantity": 100, "unit": "g"},
            {"name": "butter", "quantity": 1, "unit": "tbsp"},
            {"name": "tomato puree", "quantity": 0.5, "unit": "cup"},
            {"name": "cream", "quantity": 2, "unit": "tbsp"},
            {"name": "ginger-garlic paste", "quantity": 1, "unit": "tsp"},
            {"name": "kashmiri chili powder", "quantity": 0.5, "unit": "tsp"},
        ],
        "substitutions": {
            "paneer": ["tofu", "mushrooms"],
            "cream": ["coconut cream", "cashew paste"],
        },
    },
    57: {
        "servings": 1,
        "nutrition": {"protein_g": 14, "carbs_g": 48, "fat_g": 6, "fiber_g": 12},
        "ingredients_with_quantities": [
            {"name": "kidney beans (boiled)", "quantity": 0.75, "unit": "cup"},
            {"name": "cooked rice", "quantity": 1, "unit": "cup"},
            {"name": "onion", "quantity": 0.5, "unit": "cup"},
            {"name": "tomato", "quantity": 0.5, "unit": "cup"},
            {"name": "ginger-garlic paste", "quantity": 1, "unit": "tsp"},
            {"name": "oil", "quantity": 1.5, "unit": "tsp"},
        ],
        "substitutions": {
            "kidney beans (boiled)": ["chickpeas", "black beans"],
            "cooked rice": ["brown rice", "jeera rice"],
        },
    },
    58: {
        "servings": 1,
        "nutrition": {"protein_g": 28, "carbs_g": 10, "fat_g": 18, "fiber_g": 2},
        "ingredients_with_quantities": [
            {"name": "mutton", "quantity": 200, "unit": "g"},
            {"name": "onion", "quantity": 0.75, "unit": "cup"},
            {"name": "yogurt", "quantity": 0.25, "unit": "cup"},
            {"name": "ginger-garlic paste", "quantity": 1.5, "unit": "tsp"},
            {"name": "whole spices", "quantity": 1, "unit": "tsp"},
            {"name": "oil", "quantity": 2, "unit": "tsp"},
        ],
        "substitutions": {
            "mutton": ["chicken", "lamb"],
            "yogurt": ["thick curd", "plant yogurt"],
        },
    },
    59: {
        "servings": 1,
        "nutrition": {"protein_g": 14, "carbs_g": 12, "fat_g": 12, "fiber_g": 2},
        "ingredients_with_quantities": [
            {"name": "eggs", "quantity": 2, "unit": "pieces"},
            {"name": "onion", "quantity": 0.5, "unit": "cup"},
            {"name": "tomato", "quantity": 0.5, "unit": "cup"},
            {"name": "ginger-garlic paste", "quantity": 1, "unit": "tsp"},
            {"name": "garam masala", "quantity": 0.25, "unit": "tsp"},
            {"name": "oil", "quantity": 1.5, "unit": "tsp"},
        ],
        "substitutions": {
            "eggs": ["paneer", "tofu"],
        },
    },
    60: {
        "servings": 1,
        "nutrition": {"protein_g": 7, "carbs_g": 46, "fat_g": 12, "fiber_g": 4},
        "ingredients_with_quantities": [
            {"name": "whole wheat dough", "quantity": 1, "unit": "ball"},
            {"name": "potato (boiled, mashed)", "quantity": 1, "unit": "medium"},
            {"name": "onion", "quantity": 2, "unit": "tbsp"},
            {"name": "green chili", "quantity": 1, "unit": "piece"},
            {"name": "coriander", "quantity": 2, "unit": "tbsp"},
            {"name": "ghee / butter", "quantity": 1, "unit": "tsp"},
        ],
        "substitutions": {
            "potato (boiled, mashed)": ["sweet potato", "paneer filling"],
            "ghee / butter": ["oil", "vegan butter"],
        },
    },
}

DEFAULT_NUTRITION = {"protein_g": 0, "carbs_g": 0, "fat_g": 0, "fiber_g": 0}


class RecommendRequest(BaseModel):
    time_available: int = 999
    mood: str = ""          # "quick" | "healthy" | "comfort" | "" (any)
    diet: str = ""          # "veg" | "non-veg" | "" (any)
    mode: Literal["normal", "decide"] = "normal"
    ingredients: list[str] | None = None
    category: str | None = None
    name_query: str | None = None   # free-text: filter by name or key ingredient
    allergies: list[str] | None = None   # e.g. ["gluten","dairy","nuts"]
    cuisines: list[str] | None = None    # multi-cuisine picks from onboarding


class TrackRequest(BaseModel):
    action: Literal["view", "cook", "decide"]
    recipe_id: str


class MealPlanRequest(BaseModel):
    days: int = 7
    meals_per_day: int = 3
    time_available: int = 30
    diet: str = ""          # "veg" | "non-veg" | "" (any)
    mood: str | None = None
    category: str | None = None
    allergies: list[str] | None = None
    cuisines: list[str] | None = None


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

    if time_minutes <= time_available and time_available < 999:
        parts.append(f"Ready in {time_minutes} mins.")

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


# ── Difficulty helper (runtime) ───────────────────────────────────────────────
# Mirrors seed_mealdb._calc_difficulty so that existing DB records (seeded with
# "difficulty": "medium" before the fix) return the correct value without a
# full DB migration.

_HARD_TECHNIQUES: frozenset[str] = frozenset({
    "marinate", "deglaze", "knead", "fold in", "fold the",
    "caramelize", "caramelise", "reduce until", "blanch", "julienne",
    "flambe", "baste", "saute", "braise", "braising",
    "clarify", "emulsify", "render the", "deep-fry", "deep fry",
    "tempering", "proof the", "proofing", "whisk until stiff",
    "butterfly", "truss", "debone", "score the",
})


def _calc_difficulty(steps_text: str, time_min: int) -> str:
    """
    Estimate recipe difficulty from step count, hard technique keywords,
    and estimated cooking time.

    easy   → ≤4 steps, no hard techniques, ≤20 min
    hard   → ≥9 steps OR ≥3 hard techniques OR ≥50 min
    medium → everything else
    """
    if not steps_text:
        return "medium"
    steps = [s.strip() for s in steps_text.split(";") if s.strip()]
    n = len(steps)
    combined = steps_text.lower()
    hard_count = sum(1 for t in _HARD_TECHNIQUES if t in combined)
    if n <= 4 and hard_count == 0 and time_min <= 20:
        return "easy"
    if n >= 9 or hard_count >= 3 or time_min >= 50:
        return "hard"
    return "medium"


def recipe_summary(recipe) -> dict:
    enrichment = get_recipe_enrichment(recipe)
    # For MealDB records seeded before the difficulty fix, compute on the fly
    # so the API always returns an accurate value without a DB migration.
    if recipe.get("source") == "mealdb":
        difficulty = _calc_difficulty(
            recipe.get("steps", ""),
            recipe.get("time_minutes", 25),
        )
    else:
        difficulty = recipe["difficulty"]
    return {
        "id": int(recipe["id"]),
        "name": recipe["name"],
        "time_minutes": recipe["time_minutes"],
        "calories": recipe["calories"],
        "servings": enrichment["servings"],
        "nutrition": enrichment["nutrition"],
        "difficulty": difficulty,
        "diet": recipe["diet"],
        "tags": recipe["tags"],
        "category": recipe.get("category", "other"),
        "image_url": recipe.get("image_url", ""),
        "ingredients_preview": recipe.get("ingredients_list", [])[:5],
        "ingredients_with_quantities": enrichment["ingredients_with_quantities"][:5],
    }


INDEX_PATH = Path(__file__).resolve().parent / "index.html"
interactions: list[dict] = []          # in-memory log (used by /interactions)
recent_suggestions: list = []


# ── Per-user personalization ──────────────────────────────────────────────────
# Each user's recommendations are driven ONLY by their own cook history.
# (Replaces the previous global blend where everyone's history was mixed together.)
import time as _time

_PREF_KEYS = (
    "quick", "healthy", "comfort", "veg", "non-veg",
    "north-indian", "south-indian", "continental", "chinese",
    "snacks", "sweets", "drinks", "salad", "other",
)
_user_profile_cache: dict[str, tuple[dict, dict, float]] = {}  # user_id -> (prefs, cook_counts, ts)
_USER_PROFILE_TTL = 120.0  # seconds — recompute from DB at most this often per user


def _empty_prefs() -> dict[str, int]:
    return {k: 0 for k in _PREF_KEYS}


def _profile_from_events(events: list[dict], recipes: list[dict]) -> tuple[dict, dict]:
    """Build (preferences, cook_counts) from a list of interaction events."""
    prefs = _empty_prefs()
    cook_counts: dict = {}
    recipe_map = {int(r["id"]): r for r in recipes}
    for event in events:
        if event.get("action") != "cook":
            continue
        code = event.get("recipe_id")
        cook_counts[code] = cook_counts.get(code, 0) + 1
        tid = parse_tracked_recipe_id(code)
        if tid is None:
            continue
        recipe = recipe_map.get(tid)
        if recipe is None:
            continue
        for tag in recipe.get("tags", []):
            if tag in prefs:
                prefs[tag] += 1
        diet = (recipe.get("diet") or "").strip().lower()
        if diet in prefs:
            prefs[diet] += 1
        cat = (recipe.get("category") or "").strip().lower()
        if cat in prefs:
            prefs[cat] += 1
    return prefs, cook_counts


def get_user_profile(user_id: str | None, recipes: list[dict]) -> tuple[dict, dict]:
    """
    Return (preferences, cook_counts) for a user, briefly cached.
    Anonymous users (user_id is None) get a neutral profile — no personalization —
    so one user's history can never influence another's recommendations.
    """
    if not user_id:
        return _empty_prefs(), {}
    now = _time.monotonic()
    cached = _user_profile_cache.get(user_id)
    if cached and now - cached[2] < _USER_PROFILE_TTL:
        return cached[0], cached[1]
    events = _db.load_user_interactions(user_id, 500)
    prefs, cook_counts = _profile_from_events(events, recipes)
    _user_profile_cache[user_id] = (prefs, cook_counts, now)
    return prefs, cook_counts


def invalidate_user_profile(user_id: str | None) -> None:
    """Drop a user's cached profile so their next /recommend reflects a fresh cook."""
    if user_id:
        _user_profile_cache.pop(user_id, None)


@app.on_event("startup")
async def load_recipes_on_startup():
    """
    Startup sequence:
      1. Seed CSV data (idempotent, fast).
      2. Load all recipes from Supabase into app.state.recipes.
      3. Load persisted interactions from Supabase (per-user prefs build on demand).
      4. Run one-time DB migrations in background (difficulty + category fixes).
      5. Kick off TheMealDB seeding as a background task.
    Falls back gracefully if Supabase / TheMealDB is unreachable.
    """
    from seed_mealdb import seed_from_csv, seed_from_mealdb, backfill_csv_images

    # Always upsert CSV rows so new additions are picked up on each deploy
    seed_from_csv(force=True)

    # Serve requests immediately with whatever is in the DB
    app.state.recipes = _db.load_all_recipes()
    print(f"[startup] Loaded {len(app.state.recipes)} recipes from DB.")

    # ── Restore recent interaction log from Supabase (for /interactions) ──────
    # Per-user preferences are built on demand per request (get_user_profile),
    # so no global preference rebuild is needed here anymore.
    persisted = _db.load_recent_interactions(500)
    if persisted:
        interactions.extend(persisted)
        print(f"[startup] Restored {len(persisted)} interactions from Supabase.")

    # ── Background tasks (non-blocking) ──────────────────────────────────────
    async def _bg_mealdb_seed():
        try:
            added = await seed_from_mealdb()
            if added > 0:
                app.state.recipes = _db.load_all_recipes()
                print(f"[startup] Refreshed recipe list: {len(app.state.recipes)} total.")
        except Exception as exc:
            print(f"[startup] TheMealDB background seed failed (non-fatal): {exc}")

    async def _bg_migrations():
        """One-time fixes: difficulty, categories, and CSV image backfill."""
        # Fix hardcoded "medium" difficulty in existing MealDB rows
        try:
            fixed = _db.fix_mealdb_difficulty(_calc_difficulty)
            if fixed:
                app.state.recipes = _db.load_all_recipes()
        except Exception as exc:
            print(f"[startup] difficulty migration non-fatal: {exc}")

        # Fix wrong category mappings in existing MealDB rows
        try:
            _db.fix_mealdb_categories()
        except Exception as exc:
            print(f"[startup] category migration non-fatal: {exc}")

        # Backfill images for CSV recipes that have no image_url
        try:
            filled = await backfill_csv_images()
            if filled > 0:
                app.state.recipes = _db.load_all_recipes()
                print(f"[startup] Recipes reloaded after image backfill ({len(app.state.recipes)} total).")
        except Exception as exc:
            print(f"[startup] CSV image backfill non-fatal: {exc}")

    try:
        asyncio.create_task(_bg_mealdb_seed())
        asyncio.create_task(_bg_migrations())
    except RuntimeError:
        # No running event loop (e.g. sync test client) — skip background tasks
        pass


def get_loaded_recipes(request: Request):
    return getattr(request.app.state, "recipes", [])


@app.get("/")
def home():
    return FileResponse(INDEX_PATH)


@app.get("/health")
def health():
    return {"status": "ok"}


# Maps user-typed terms to internal category slugs
_CATEGORY_KEYWORD_MAP: dict[str, str] = {
    "north indian": "north-indian",
    "north-indian": "north-indian",
    "northindian": "north-indian",
    "north india": "north-indian",
    "south indian": "south-indian",
    "south-indian": "south-indian",
    "southindian": "south-indian",
    "south india": "south-indian",
    "chinese": "chinese",
    "china": "chinese",
    "continental": "continental",
    "western": "continental",
    "european": "continental",
    "drink": "drinks",
    "drinks": "drinks",
    "juice": "drinks",
    "smoothie": "drinks",
    "smoothies": "drinks",
    "beverage": "drinks",
    "beverages": "drinks",
    "shake": "drinks",
    "snack": "snacks",
    "snacks": "snacks",
    "starter": "snacks",
    "starters": "snacks",
    "appetizer": "snacks",
    "appetizers": "snacks",
    "salad": "salad",
    "salads": "salad",
    # International cuisines mapped to nearest available category
    "thai": "continental",
    "japanese": "continental",
    "korean": "continental",
    "vietnamese": "continental",
    "mexican": "continental",
    "italian": "continental",
    "french": "continental",
    "mediterranean": "continental",
    "asian": "chinese",
    "indo chinese": "chinese",
    "indo-chinese": "chinese",
    "manchurian": "chinese",
    "noodles": "chinese",
    "fried rice": "chinese",
}

# Maps user-typed diet terms to internal diet values
_DIET_KEYWORD_MAP: dict[str, str] = {
    "vegan": "veg",
    "vegetarian": "veg",
    "veg": "veg",
    "veggie": "veg",
    "plant based": "veg",
    "plant-based": "veg",
    "non-veg": "non-veg",
    "non veg": "non-veg",
    "nonveg": "non-veg",
    "meat": "non-veg",
    "meaty": "non-veg",
    "non vegetarian": "non-veg",
}


@app.get("/browse")
def browse_recipes(
    diet: str = "",
    category: str = "",
    max_time: int = 0,
    max_cal: int = 0,
    sort: str = "popular",   # popular | quick | healthy | calories
    limit: int = 24,
    offset: int = 0,
    request: Request = None,
):
    """
    Browse all recipes with optional filters — no text query needed.
    Use for the Browse sheet, cuisine pages, diet pages, etc.

    Filters (all optional, combinable):
      diet      — veg | non-veg
      category  — north-indian | south-indian | continental | chinese | snacks | other
      max_time  — maximum cooking time in minutes (0 = no limit)
      max_cal   — maximum calories (0 = no limit)

    Sort:
      popular   — shuffle with slight preference for lower id (seeded by day)
      quick     — time_minutes asc
      healthy   — calories asc
      calories  — calories desc
    """
    import random as _random
    recipes = get_loaded_recipes(request)

    diet_f     = (diet     or "").strip().lower()
    category_f = normalize_category(category or "")
    max_time_f = max(0, max_time)
    max_cal_f  = max(0, max_cal)

    pool = []
    for r in recipes:
        if diet_f and r.get("diet", "").lower() != diet_f:
            continue
        if category_f and category_f != "all":
            if r.get("category", "").lower() != category_f:
                continue
        if max_time_f and (r.get("time_minutes") or 999) > max_time_f:
            continue
        if max_cal_f and (r.get("calories") or 999) > max_cal_f:
            continue
        pool.append(r)

    if sort == "quick":
        pool.sort(key=lambda r: (r.get("time_minutes") or 999, r["name"]))
    elif sort == "healthy":
        pool.sort(key=lambda r: (r.get("calories") or 999, r["name"]))
    elif sort == "calories":
        pool.sort(key=lambda r: (-(r.get("calories") or 0), r["name"]))
    else:
        # "popular" — deterministic daily shuffle so each user gets the same order
        import datetime as _dt
        seed = int(_dt.date.today().strftime("%Y%j"))
        rng  = _random.Random(seed)
        rng.shuffle(pool)

    limit  = max(1, min(limit, 100))
    offset = max(0, offset)
    page   = pool[offset: offset + limit]
    total  = len(pool)

    from fastapi.responses import JSONResponse
    return JSONResponse(
        content=[recipe_summary(r) for r in page],
        headers={"X-Total-Count": str(total)},
    )


@app.get("/search")
def search_recipes(
    q: str,
    diet: str = "",
    category: str = "",
    max_time: int = 0,
    limit: int = 24,
    offset: int = 0,
    request: Request = None,
):
    """
    Universal search — no diet/time/category filter applied for text queries.
    Handles cuisine (japanese, continental), category (drinks, snacks),
    explicit diet intent (vegan, non-veg), ingredient names (chicken, paneer),
    and recipe names.

    Relevance tiers (higher = better):
      110 — category/cuisine keyword match OR diet intent match
      100 — exact name match
       82 — name starts with query (word-boundary bonus vs mid-word)
       80 — name starts with query
       65 — query word at start of any word in name (word-boundary bonus)
       60 — query phrase anywhere in name
       50 — all query words in name (multi-word like "butter chicken")
       30 — any query word in name
       22 — query phrase in ingredients (word-boundary bonus)
       20 — query phrase in ingredients
       12 — any query word in ingredients (word-boundary bonus)
       10 — any query word in ingredients

    Pagination: use offset + limit. Total matched count is in X-Total-Count header.
    """
    recipes = get_loaded_recipes(request)
    q_lower = (q or "").strip().lower()
    if len(q_lower) < 2:
        return []

    words = [w for w in q_lower.split() if w]

    # ── Detect special intent keywords ────────────────────────────────────────
    # Check full query first, then individual words (e.g. "thai dish" → "thai" → continental)
    target_category = _CATEGORY_KEYWORD_MAP.get(q_lower)
    if not target_category:
        for w in words:
            if w in _CATEGORY_KEYWORD_MAP:
                target_category = _CATEGORY_KEYWORD_MAP[w]
                break
    target_diet = _DIET_KEYWORD_MAP.get(q_lower)
    if not target_diet:
        for w in words:
            if w in _DIET_KEYWORD_MAP:
                target_diet = _DIET_KEYWORD_MAP[w]
                break

    scored: list[tuple[int, dict]] = []

    for recipe in recipes:
        name_lower  = recipe["name"].lower()
        recipe_cat  = (recipe.get("category") or "").strip().lower()
        recipe_diet = recipe["diet"].strip().lower()
        ing_text    = " ".join(recipe.get("ingredients_list", []))
        name_words  = name_lower.split()   # for word-boundary checks

        score = 0

        # ── 1. Category / cuisine intent ─────────────────────────────────────
        if target_category:
            if recipe_cat == target_category:
                score = 110
            elif any(w in name_lower for w in words):
                score = 70
            else:
                continue

        # ── 2. Explicit diet intent (vegan / non-veg as sole query) ──────────
        elif target_diet:
            if recipe_diet == target_diet:
                score = 110
            else:
                continue

        # ── 3. Universal text matching — NO diet filter ───────────────────────
        else:
            if q_lower == name_lower:
                score = 100
            elif name_lower.startswith(q_lower):
                # bonus if query matches at a word boundary
                score = 82 if (len(name_words) > 1 and any(w.startswith(q_lower) for w in name_words[1:])) else 80
            elif q_lower in name_lower:
                # bonus when query is at the start of any word inside the name
                score = 65 if any(w.startswith(q_lower) for w in name_words) else 60
            elif len(words) > 1 and all(w in name_lower for w in words):
                score = 50
            elif any(w in name_lower for w in words):
                # bonus when any query word starts a name-word (e.g. "dal" in "dal tadka")
                score = 32 if any(nw.startswith(w) for w in words for nw in name_words) else 30
            elif q_lower in ing_text:
                ing_words = ing_text.split()
                score = 22 if any(iw.startswith(q_lower) for iw in ing_words) else 20
            elif len(words) > 1 and all(w in ing_text for w in words):
                score = 15
            elif any(w in ing_text for w in words):
                ing_words = ing_text.split()
                score = 12 if any(iw.startswith(w) for w in words for iw in ing_words) else 10
            else:
                continue  # no match

        scored.append((score, recipe))

    # Sort: relevance desc, then name asc for stable ordering
    scored.sort(key=lambda x: (-x[0], x[1]["name"]))

    # ── Post-filter by optional sidebar filters ───────────────────────────────
    diet_f     = (diet     or "").strip().lower()
    category_f = normalize_category(category or "")
    max_time_f = max(0, max_time)

    if diet_f or (category_f and category_f != "all") or max_time_f:
        filtered = []
        for score, r in scored:
            if diet_f and r.get("diet", "").lower() != diet_f:
                continue
            if category_f and category_f != "all":
                if r.get("category", "").lower() != category_f:
                    continue
            if max_time_f and (r.get("time_minutes") or 999) > max_time_f:
                continue
            filtered.append((score, r))
        scored = filtered

    limit   = max(1, min(limit, 100))
    offset  = max(0, offset)
    total   = len(scored)
    page    = scored[offset: offset + limit]

    from fastapi.responses import JSONResponse
    return JSONResponse(
        content=[recipe_summary(r) for _, r in page],
        headers={"X-Total-Count": str(total)},
    )


# ── Allergen keyword map ──────────────────────────────────────────────────────
import re as _re_allergen

# Maps allergy name → ingredient terms to screen for.
# Matching is WORD-BOUNDARY based (with optional trailing "s"), so:
#   • "egg" does NOT match "eggplant", "wheat" does NOT match "buckwheat"
#     (buckwheat is naturally gluten-free), "nut" does NOT match "coconut".
#   • lists are kept deliberately broad (incl. synonyms) — for an allergy filter,
#     missing a real allergen is far worse than over-removing a safe dish.
_ALLERGEN_KEYWORDS: dict[str, list[str]] = {
    "gluten":  ["wheat", "whole wheat", "flour", "maida", "atta", "bread", "pasta",
                "noodle", "macaroni", "vermicelli", "semolina", "sooji", "rava",
                "roti", "paratha", "puri", "poori", "naan", "kulcha", "bhatura",
                "barley", "rye", "malt", "bran", "couscous", "bulgur", "farro",
                "durum", "spelt", "seitan", "cracker", "biscuit", "bun", "toast"],
    "dairy":   ["milk", "butter", "cheese", "cream", "yogurt", "yoghurt", "curd",
                "dahi", "paneer", "ghee", "khoya", "mawa", "condensed milk",
                "buttermilk", "whey", "casein", "lassi", "malai", "rabri", "rabdi",
                "custard", "kheer", "kulfi", "shrikhand", "chhena"],
    "nuts":    ["almond", "cashew", "kaju", "peanut", "groundnut", "walnut",
                "pistachio", "pista", "pine nut", "hazelnut", "pecan", "chestnut",
                "macadamia", "marzipan", "praline", "nougat", "nutella", "nut"],
    "eggs":    ["egg", "omelette", "omelet", "frittata", "mayonnaise", "mayo",
                "meringue", "aioli", "albumen"],
    "seafood": ["fish", "prawn", "shrimp", "crab", "lobster", "oyster", "mussel",
                "squid", "calamari", "octopus", "tuna", "salmon", "cod", "mackerel",
                "sardine", "anchovy", "clam", "scallop", "caviar", "roe", "surimi",
                "krill", "hilsa", "pomfret", "tilapia", "rohu", "catla", "bhetki",
                "bhekti"],
    "soy":     ["soy", "soya", "tofu", "tempeh", "miso", "edamame", "tamari", "tvp"],
}

# Terms that must NEVER trigger an allergen even though they look similar — a
# second safety guard for word-boundary edge cases (e.g. "water chestnut" is an
# aquatic vegetable, not a tree nut).
_ALLERGEN_SAFE_TERMS: dict[str, list[str]] = {
    "nuts": ["water chestnut", "nutmeg", "butternut", "coconut"],
    # Naturally gluten-free flours/grains — stripped before matching so the
    # generic "flour" keyword doesn't wrongly exclude rice/besan/millet dishes
    # (common staples) for gluten-sensitive users.
    "gluten": ["buckwheat flour", "buckwheat", "rice flour", "corn flour",
               "cornflour", "cornstarch", "gram flour", "chickpea flour", "besan",
               "almond flour", "coconut flour", "millet flour", "jowar flour",
               "bajra flour", "ragi flour", "tapioca flour", "potato flour",
               "oat flour"],
}

# Precompiled, word-boundary matchers (case-insensitive, optional plural "s").
_ALLERGEN_RE: dict[str, "_re_allergen.Pattern"] = {
    allergy: _re_allergen.compile(
        r"\b(?:" + "|".join(_re_allergen.escape(k) for k in kws) + r")s?\b",
        _re_allergen.IGNORECASE,
    )
    for allergy, kws in _ALLERGEN_KEYWORDS.items()
}
_ALLERGEN_SAFE_RE: dict[str, "_re_allergen.Pattern"] = {
    # Longest phrases first so e.g. "buckwheat flour" is stripped whole rather
    # than matching the shorter "buckwheat" and leaving "flour" behind.
    allergy: _re_allergen.compile(
        r"\b(?:" + "|".join(
            _re_allergen.escape(k) for k in sorted(terms, key=len, reverse=True)
        ) + r")s?\b",
        _re_allergen.IGNORECASE,
    )
    for allergy, terms in _ALLERGEN_SAFE_TERMS.items()
}


def _recipe_has_allergen(recipe: dict, allergy: str) -> bool:
    """Return True if the recipe contains any ingredient matching the allergy."""
    rx = _ALLERGEN_RE.get(allergy.lower())
    if rx is None:
        return False
    ingredient_text = " ".join(recipe.get("ingredients_list", []))
    combined = ingredient_text + " " + recipe.get("name", "")

    # Strip out known-safe lookalikes first so they can't trigger a match.
    safe_rx = _ALLERGEN_SAFE_RE.get(allergy.lower())
    if safe_rx is not None:
        combined = safe_rx.sub(" ", combined)

    return bool(rx.search(combined))


def apply_allergy_filter(recipes: list[dict], allergies: list[str] | None) -> list[dict]:
    """Remove recipes that contain any of the user's allergens.
    Keeps all recipes if allergies is None / empty."""
    if not allergies:
        return recipes
    clean_allergies = [a.strip().lower() for a in allergies if a.strip().lower() in _ALLERGEN_KEYWORDS]
    if not clean_allergies:
        return recipes
    safe = [r for r in recipes if not any(_recipe_has_allergen(r, a) for a in clean_allergies)]
    # Safety net: if allergy filter removed everything, return original pool
    # (better to show something than an empty page)
    return safe if safe else recipes


@app.post("/recommend")
def recommend(
    payload: RecommendRequest,
    request: Request,
    user: dict | None = Depends(get_optional_user),
):
    ranked = []
    recipes = get_loaded_recipes(request)
    diet = payload.diet
    category = normalize_category(payload.category)

    # Per-user personalization: preferences + cook history for THIS user only.
    # Anonymous users get a neutral profile (no cross-user contamination).
    prefs, cook_counts = get_user_profile(user["id"] if user else None, recipes)

    # ── Diet filter ───────────────────────────────────────────────────────────
    if diet:
        filtered_recipes = [
            r for r in recipes
            if r["diet"].strip().lower() == diet.strip().lower()
        ]
        if not filtered_recipes:
            filtered_recipes = list(recipes)   # broaden if nothing matches
    else:
        filtered_recipes = list(recipes)   # "Any" diet — show all

    # ── Allergy filter ────────────────────────────────────────────────────────
    # Applied early so all downstream filters operate on a safe pool.
    filtered_recipes = apply_allergy_filter(filtered_recipes, payload.allergies)

    # ── Time filter ───────────────────────────────────────────────────────────
    # Prefer respecting the user's time limit; if too strict, fall back to diet-only.
    # Skip time filter when ingredients are present — ingredient matching is the primary
    # constraint, so we should not pre-eliminate recipes before the ingredient step.
    has_ingredients = bool(payload.ingredients)
    if not has_ingredients and payload.time_available and payload.time_available < 999:
        time_filtered_recipes = [r for r in filtered_recipes if int(r["time_minutes"]) <= payload.time_available]
        if time_filtered_recipes:
            filtered_recipes = time_filtered_recipes

    # ── Category / multi-cuisine filter ──────────────────────────────────────
    # Multi-cuisine (payload.cuisines) takes precedence over single category.
    # Falls back gracefully when too narrow.
    cuisines_norm = [normalize_category(c) for c in (payload.cuisines or []) if c]
    cuisines_norm = [c for c in cuisines_norm if c]   # drop empty strings

    if cuisines_norm:
        # Match any of the selected cuisines
        multi_cat_filtered = [
            r for r in filtered_recipes
            if (r.get("category") or "").strip().lower() in cuisines_norm
        ]
        if multi_cat_filtered:
            filtered_recipes = multi_cat_filtered
        # else fall through — don't narrow down further
    elif category:
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

        # Personalization bonus: tags + diet + cuisine category learned from THIS
        # user's cook history (prefs is neutral/empty for anonymous users).
        preference_bonus = 0.0
        for tag in recipe.get("tags", []):
            preference_bonus += min(prefs.get(tag, 0), 10) * 0.5
        preference_bonus += min(prefs.get(recipe.get("diet", ""), 0), 10) * 0.5
        recipe_cat = (recipe.get("category") or "").strip().lower()
        preference_bonus += min(prefs.get(recipe_cat, 0), 10) * 0.4
        score += preference_bonus

        # Ingredient match boost (only when ingredient filtering is active).
        if normalized_user_ingredients and int(recipe["id"]) in ingredient_match_ids:
            score += 2
        # Single-category boost
        if category and (recipe.get("category") or "").strip().lower() == category:
            score += 1.5
            reasons.append(f"matches {category.replace('-', ' ')} preference")
        # Multi-cuisine boost: recipe matches any of the user's preferred cuisines
        if cuisines_norm and recipe_cat in cuisines_norm:
            score += 1.2
            reasons.append(f"matches your cuisine preference")
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


@app.get("/for-you")
def for_you_recommendations(
    liked_ids: str = "",       # comma-separated recipe IDs the user has cooked/saved
    limit: int = 12,
    request: Request = None,
):
    """
    Content-based personalised recommendations.

    Derives the user's taste profile from the IDs of recipes they've cooked/saved,
    then scores the full catalogue by category + tag overlap and returns the
    top matches (excluding the seed recipes themselves).

    liked_ids — comma-separated integer IDs (e.g. "3,14,27")
    limit     — max recipes to return (capped at 50)
    """
    import random as _rnd
    recipes = get_loaded_recipes(request)
    limit = max(1, min(limit, 50))

    # Parse and resolve the seed recipes
    raw_ids = [s.strip() for s in liked_ids.split(",") if s.strip().isdigit()]
    seed_ids = {int(x) for x in raw_ids}

    if not seed_ids:
        # Cold start: return popular shuffle (same as browse default)
        import datetime as _dt
        seed = int(_dt.date.today().strftime("%Y%j"))
        rng  = _rnd.Random(seed)
        pool = list(recipes)
        rng.shuffle(pool)
        return [recipe_summary(r) for r in pool[:limit]]

    seed_recipes = [r for r in recipes if int(r["id"]) in seed_ids]

    # Build preference counters from seed recipes
    cat_counts: dict[str, int] = {}
    tag_counts: dict[str, int] = {}
    diet_pref: str | None = None
    diet_votes: dict[str, int] = {}

    for r in seed_recipes:
        cat = (r.get("category") or "").lower().strip()
        if cat:
            cat_counts[cat] = cat_counts.get(cat, 0) + 1
        for tag in (r.get("tags") or "").lower().split(","):
            tag = tag.strip()
            if tag:
                tag_counts[tag] = tag_counts.get(tag, 0) + 1
        diet = (r.get("diet") or "").lower().strip()
        if diet:
            diet_votes[diet] = diet_votes.get(diet, 0) + 1

    # Majority diet (only enforce if strongly consistent — ≥ 70 % of seeds)
    if diet_votes:
        top_diet, top_count = max(diet_votes.items(), key=lambda x: x[1])
        if top_count / len(seed_recipes) >= 0.7:
            diet_pref = top_diet

    def score(r: dict) -> float:
        if int(r["id"]) in seed_ids:
            return -1.0                         # exclude seed recipes from results
        s = 0.0
        cat = (r.get("category") or "").lower().strip()
        s += cat_counts.get(cat, 0) * 3.0      # category match is worth 3 pts each
        for tag in (r.get("tags") or "").lower().split(","):
            tag = tag.strip()
            s += tag_counts.get(tag, 0) * 1.0  # tag match 1 pt each
        if diet_pref and (r.get("diet") or "").lower().strip() != diet_pref:
            s *= 0.4                            # penalise mismatched diet
        return s

    scored = sorted(recipes, key=score, reverse=True)
    # Exclude seed IDs and zero-score recipes; fill remainder randomly if needed
    good    = [r for r in scored if score(r) > 0]
    filler  = [r for r in scored if score(r) == 0]
    _rnd.shuffle(filler)
    result  = (good + filler)[:limit]

    return [recipe_summary(r) for r in result]


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

    # Diet filter (empty string = any)
    if payload.diet:
        candidates = [
            r for r in recipes
            if r["diet"].strip().lower() == payload.diet.strip().lower()
            and int(r["time_minutes"]) <= int(payload.time_available)
        ]
        if not candidates:
            candidates = [r for r in recipes if int(r["time_minutes"]) <= int(payload.time_available)]
    else:
        candidates = [r for r in recipes if int(r["time_minutes"]) <= int(payload.time_available)]

    # Allergy filter
    candidates = apply_allergy_filter(candidates, payload.allergies)

    # Category / multi-cuisine filter
    plan_cuisines = [normalize_category(c) for c in (payload.cuisines or []) if c]
    plan_cuisines = [c for c in plan_cuisines if c]
    if plan_cuisines:
        cuisine_matches = [
            r for r in candidates
            if (r.get("category") or "").strip().lower() in plan_cuisines
        ]
        if cuisine_matches:
            candidates = cuisine_matches
    elif category:
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
def track_interaction(
    payload: TrackRequest,
    request: Request,
    user: dict | None = Depends(get_optional_user),
):
    user_id = user["id"] if user else None

    interaction = {
        "action": payload.action,
        "recipe_id": payload.recipe_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    interactions.append(interaction)

    # Persist to Supabase (scoped to this user) so personalisation survives restarts.
    _db.save_interaction(payload.action, payload.recipe_id, user_id=user_id)

    # A new cook changes this user's profile — drop their cache so the next
    # /recommend rebuilds it from fresh history.
    if payload.action == "cook":
        invalidate_user_profile(user_id)

    return interaction


@app.get("/interactions")
def get_interactions():
    return interactions


# ── Saved recipes (Supabase-backed, auth-required) ────────────────────────────

class SaveRecipeRequest(BaseModel):
    recipe_id: int
    recipe_data: dict


@app.get("/saved")
def list_saved(user: dict = Depends(get_current_user)):
    """Return all saved recipes for the authenticated user, newest first."""
    result = (
        supabase_admin
        .table("saved_recipes")
        .select("recipe_id, recipe_data, saved_at")
        .eq("user_id", user["id"])
        .order("saved_at", desc=True)
        .execute()
    )
    return result.data or []


@app.post("/saved", status_code=201)
def save_recipe(payload: SaveRecipeRequest, user: dict = Depends(get_current_user)):
    """Save a recipe for the authenticated user (upsert)."""
    supabase_admin.table("saved_recipes").upsert(
        {
            "user_id": user["id"],
            "recipe_id": payload.recipe_id,
            "recipe_data": payload.recipe_data,
            "saved_at": datetime.now(timezone.utc).isoformat(),
        },
        on_conflict="user_id,recipe_id",
    ).execute()
    return {"saved": True, "recipe_id": payload.recipe_id}


@app.delete("/saved/{recipe_id}", status_code=200)
def unsave_recipe(recipe_id: int, user: dict = Depends(get_current_user)):
    """Remove a saved recipe for the authenticated user."""
    supabase_admin.table("saved_recipes").delete().match(
        {"user_id": user["id"], "recipe_id": recipe_id}
    ).execute()
    return {"removed": True, "recipe_id": recipe_id}


# ── Web Push notifications ────────────────────────────────────────────────────

import json as _json
from concurrent.futures import ThreadPoolExecutor as _TPE

_VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY", "")
_VAPID_CLAIMS      = {"sub": "mailto:punyachatgpt@gmail.com"}
_PUSH_SECRET       = os.getenv("PUSH_SECRET", "")   # shared secret for /push/send
_push_executor     = _TPE(max_workers=4)

_DAILY_MESSAGES = [
    ("🍳 What's cooking tonight?",       "Your personalised picks are ready. Tap to see."),
    ("🌅 Start the week deliciously",    "Fresh recipe ideas are waiting for you."),
    ("🍛 Tonight's dinner sorted",       "Check your personalised picks on Simmer."),
    ("🥘 Mid-week meal inspiration",     "Don't let dinner be boring — see today's picks."),
    ("🍳 Almost the weekend!",           "Treat yourself to something great tonight."),
    ("🎉 Friday feast time",             "Your weekend cooking starts here."),
    ("☀️ Sunday special",               "Make something memorable today."),
]


class PushSubscribeRequest(BaseModel):
    endpoint: str
    p256dh: str
    auth: str


# ── AI Chef Chat ──────────────────────────────────────────────────────────────

class AIChatMessage(BaseModel):
    role: str          # "user" | "ai"
    text: str = ""
    thinking: bool = False

class AIChatRequest(BaseModel):
    message: str
    history: list[AIChatMessage] = []
    diet: str = ""
    category: str = ""
    ingredients: list[str] = []


def _build_chef_system_prompt(payload: "AIChatRequest") -> str:
    prefs: list[str] = []
    if payload.diet:        prefs.append(f"diet: {payload.diet}")
    if payload.category:    prefs.append(f"favourite cuisine: {payload.category.replace('-', ' ')}")
    if payload.ingredients: prefs.append(f"has in fridge: {', '.join(payload.ingredients[:8])}")

    return f"""You are Simmer's AI cooking assistant — warm, expert, and concise.
You specialise in Indian home cooking but know international cuisine too.
You help with: recipe ideas, cooking techniques, ingredient substitutions, and dietary adaptations.
{f"User context — {'; '.join(prefs)}." if prefs else ""}

Available recipe categories in the app: north-indian, south-indian, continental, chinese, snacks, sweets, drinks, salad.
International cuisine mapping guide (use these when generating SUGGEST queries):
- Thai, Japanese, Korean, Vietnamese → use "continental" or key ingredients like "noodles", "stir fry", "coconut"
- Mexican, Italian, French, Mediterranean → use "continental"
- Chinese, Indo-Chinese → use "chinese"

Rules:
- Reply in 2-4 short sentences. Be specific and practical, never vague.
- If the user asks for recipe suggestions or ideas, end your reply with exactly:
  SUGGEST: <short search query>
  Example: SUGGEST: quick veg north indian dinner under 20 minutes
  Example: SUGGEST: spicy chicken continental
  Example: SUGGEST: paneer with coconut curry
- The SUGGEST query must use ingredients, dish names, or categories from the available list above.
- If user asks for a cuisine not in the database (thai, mexican, etc.), map it to the nearest category and suggest similar dishes.
- Only add SUGGEST when they explicitly want recipe ideas. Never for technique/substitution questions.
- Do not repeat "SUGGEST:" more than once."""


def _parse_chef_reply(full_text: str) -> tuple[str, str]:
    recipe_query = ""
    if "SUGGEST:" in full_text:
        parts        = full_text.split("SUGGEST:", 1)
        full_text    = parts[0].strip()
        recipe_query = parts[1].strip().splitlines()[0].strip()
    return full_text, recipe_query


class GeminiRateLimitError(Exception):
    """Raised when Gemini returns 429 after all retries across all fallback models."""

class GeminiConfigError(Exception):
    """Raised when Gemini returns a non-retryable error (bad key, bad model, etc.)."""

# Fallback chain: primary model first, then lighter alternatives
_GEMINI_FALLBACK_MODELS = [
    _GEMINI_MODEL,          # configured model (default: gemini-2.0-flash)
    "gemini-2.0-flash-lite",
    "gemini-2.5-flash",
]

async def _call_gemini_model(client: "httpx.AsyncClient", api_key: str, model: str, body: dict) -> str:
    """Try one model with up to 3 attempts on 429. Returns text or raises."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    waits = [0, 4, 8]
    for attempt, wait in enumerate(waits):
        if wait:
            print(f"[Gemini/{model}] 429 — retry {attempt}/{len(waits)-1} after {wait}s")
            await asyncio.sleep(wait)
        resp = await client.post(url, json=body)
        print(f"[Gemini/{model}] status={resp.status_code}")
        if resp.status_code == 429:
            continue
        # 4xx errors (401 bad key, 403 forbidden, 404 bad model) are not retryable
        if 400 <= resp.status_code < 500:
            err_body = ""
            try:
                err_body = resp.json().get("error", {}).get("message", "")
            except Exception:
                pass
            print(f"[Gemini/{model}] non-retryable {resp.status_code}: {err_body}")
            raise GeminiConfigError(f"{resp.status_code}:{model}")
        resp.raise_for_status()
        data = resp.json()
        return data["candidates"][0]["content"]["parts"][0]["text"].strip()
    raise GeminiRateLimitError(f"rate_limit:{model}")

async def _call_gemini(api_key: str, system_prompt: str, messages: list[dict], user_msg: str) -> str:
    """Call Gemini with automatic model fallback if quota is exhausted."""
    contents: list[dict] = []
    for m in messages[:-1]:
        role = "user" if m["role"] == "user" else "model"
        contents.append({"role": role, "parts": [{"text": m["content"]}]})
    contents.append({"role": "user", "parts": [{"text": user_msg}]})

    body = {
        "system_instruction": {"parts": [{"text": system_prompt}]},
        "contents": contents,
        "generationConfig": {"maxOutputTokens": 350, "temperature": 0.7},
    }

    tried = set()
    config_errors = 0
    async with httpx.AsyncClient(timeout=30.0) as client:
        for model in _GEMINI_FALLBACK_MODELS:
            if model in tried:
                continue
            tried.add(model)
            try:
                text = await _call_gemini_model(client, api_key, model, body)
                if model != _GEMINI_MODEL:
                    print(f"[Gemini] Used fallback model: {model}")
                return text
            except GeminiRateLimitError:
                print(f"[Gemini] Model {model} quota exhausted, trying next fallback…")
                continue
            except GeminiConfigError as exc:
                config_errors += 1
                print(f"[Gemini] Config error on {model}: {exc}")
                # 401/403 = bad key — no point trying other models with same key
                if "401:" in str(exc) or "403:" in str(exc):
                    raise
                # 404 = bad model name — try next model
                continue
            except Exception as exc:
                print(f"[Gemini] Unexpected error on {model}: {type(exc).__name__}: {exc}")
                continue

    if config_errors == len(tried):
        raise GeminiConfigError("all_models_failed_config")
    raise GeminiRateLimitError("all_models_exhausted")


# ── Groq (OpenAI-compatible, free tier) ───────────────────────────────────────
_GROQ_MODEL = "llama-3.3-70b-versatile"
_GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

async def _call_groq(api_key: str, system_prompt: str, messages: list[dict], user_msg: str) -> str:
    """Call Groq's OpenAI-compatible API. Returns the assistant reply text."""
    oai_messages = [{"role": "system", "content": system_prompt}]
    for m in messages[:-1]:          # history (last item is the current user msg)
        oai_messages.append({"role": m["role"], "content": m["content"]})
    oai_messages.append({"role": "user", "content": user_msg})

    body = {
        "model": _GROQ_MODEL,
        "messages": oai_messages,
        "max_tokens": 350,
        "temperature": 0.7,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(_GROQ_API_URL, json=body, headers=headers)
        if resp.status_code == 429:
            raise GeminiRateLimitError("groq_rate_limit")
        if resp.status_code != 200:
            print(f"[Groq] Error {resp.status_code}: {resp.text[:200]}")
            raise GeminiConfigError(f"groq_{resp.status_code}")
        data = resp.json()
        return data["choices"][0]["message"]["content"].strip()


@app.post("/ai-chat")
async def ai_chef_chat(payload: AIChatRequest):
    """
    AI cooking assistant — supports Anthropic Claude (ANTHROPIC_API_KEY)
    or Google Gemini Flash (GEMINI_API_KEY) as a free alternative.
    Returns a natural-language reply and an optional recipe search query.
    """
    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    groq_key      = os.getenv("GROQ_API_KEY", "").strip()
    gemini_key    = os.getenv("GEMINI_API_KEY", "").strip()

    if not anthropic_key and not groq_key and not gemini_key:
        return {
            "reply": (
                "The AI Chef needs an API key to work. "
                "Add GROQ_API_KEY to your Render environment variables — "
                "it's completely free at console.groq.com (no credit card needed)!"
            ),
            "recipe_query": payload.message,
        }

    system_prompt = _build_chef_system_prompt(payload)

    messages: list[dict] = []
    for msg in payload.history[-8:]:
        if msg.thinking or not (msg.text or "").strip():
            continue
        role = "user" if msg.role == "user" else "assistant"
        messages.append({"role": role, "content": msg.text.strip()})
    messages.append({"role": "user", "content": payload.message.strip()})

    # ── Anthropic path ────────────────────────────────────────────────────────
    if anthropic_key:
        try:
            import anthropic as _anthropic
            client   = _anthropic.Anthropic(api_key=anthropic_key)
            response = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=350,
                system=system_prompt,
                messages=messages,
            )
            full_text = (response.content[0].text or "").strip()
            reply, recipe_query = _parse_chef_reply(full_text)
            return {"reply": reply, "recipe_query": recipe_query}
        except Exception:
            pass  # fall through to next provider

    # ── Groq path (free, llama-3.3-70b) ──────────────────────────────────────
    if groq_key:
        try:
            full_text = await _call_groq(groq_key, system_prompt, messages, payload.message.strip())
            reply, recipe_query = _parse_chef_reply(full_text)
            return {"reply": reply, "recipe_query": recipe_query}
        except GeminiRateLimitError:
            return {"reply": "The kitchen is a little busy right now — please try again in a moment 🍳", "recipe_query": ""}
        except Exception:
            pass  # fall through to Gemini

    # ── Gemini path ───────────────────────────────────────────────────────────
    if gemini_key:
        try:
            full_text = await _call_gemini(gemini_key, system_prompt, messages, payload.message.strip())
            reply, recipe_query = _parse_chef_reply(full_text)
            return {"reply": reply, "recipe_query": recipe_query}
        except GeminiConfigError:
            return {"reply": "The AI Chef couldn't connect — please check your API key in Render environment variables. 🔑", "recipe_query": ""}
        except GeminiRateLimitError:
            return {"reply": "The kitchen is a little busy right now — please try again in a moment 🍳", "recipe_query": ""}
        except Exception:
            pass

    return {"reply": "The AI Chef is unavailable right now. Please try again shortly. 🍳", "recipe_query": ""}


# ── Text-to-Speech ─────────────────────────────────────────────────────────────
# gTTS wraps Google's neural TTS — sounds like a real human voice.
# Supports 30+ languages including Hindi, Tamil, Spanish, French, etc.
_TTS_LANG_MAP: dict[str, tuple[str, str]] = {
    # code    → (gTTS lang, gTTS tld)   tld changes the accent
    "en":     ("en", "com"),        # English US
    "en-gb":  ("en", "co.uk"),      # English UK
    "en-au":  ("en", "com.au"),     # English Australian
    "en-in":  ("en", "co.in"),      # English Indian accent
    "hi":     ("hi", "com"),        # Hindi
    "ta":     ("ta", "com"),        # Tamil
    "te":     ("te", "com"),        # Telugu
    "bn":     ("bn", "com"),        # Bengali
    "mr":     ("mr", "com"),        # Marathi
    "gu":     ("gu", "com"),        # Gujarati
    "pa":     ("pa", "com"),        # Punjabi
    "kn":     ("kn", "com"),        # Kannada
    "ml":     ("ml", "com"),        # Malayalam
    "es":     ("es", "com"),        # Spanish
    "fr":     ("fr", "com"),        # French
    "de":     ("de", "com"),        # German
    "ar":     ("ar", "com"),        # Arabic
    "ja":     ("ja", "com"),        # Japanese
    "ko":     ("ko", "com"),        # Korean
    "zh":     ("zh-CN", "com"),     # Chinese (Mandarin)
    "pt":     ("pt", "com"),        # Portuguese
    "ru":     ("ru", "com"),        # Russian
    "it":     ("it", "com"),        # Italian
}

@app.get("/tts")
async def text_to_speech(text: str = "", lang: str = "en"):
    """
    Convert text to natural-sounding speech via Google TTS.
    Returns MP3 audio. Used by the Cook Genie in Cook Mode.
    """
    import io
    try:
        from gtts import gTTS
    except ImportError:
        raise HTTPException(503, "TTS service not available — install gTTS")

    text = text.strip()[:500]
    if not text:
        raise HTTPException(400, "text parameter is required")

    gtts_lang, tld = _TTS_LANG_MAP.get(lang.lower(), ("en", "com"))

    try:
        buf = io.BytesIO()
        tts = gTTS(text=text, lang=gtts_lang, tld=tld, slow=False)
        tts.write_to_fp(buf)
        buf.seek(0)
    except Exception as exc:
        print(f"[TTS] gTTS error: {exc}")
        raise HTTPException(500, "TTS generation failed")

    from fastapi.responses import StreamingResponse
    return StreamingResponse(
        buf,
        media_type="audio/mpeg",
        headers={
            "Cache-Control": "public, max-age=3600",
            "Content-Disposition": "inline",
        },
    )


@app.post("/push/subscribe", status_code=201)
def push_subscribe(
    payload: PushSubscribeRequest,
    user: dict | None = Depends(get_optional_user),
):
    """Store a Web Push subscription. Works for anonymous and logged-in users."""
    row = {
        "endpoint": payload.endpoint,
        "p256dh":   payload.p256dh,
        "auth":     payload.auth,
        "user_id":  user["id"] if user else None,
    }
    supabase_admin.table("push_subscriptions").upsert(
        row, on_conflict="endpoint"
    ).execute()
    return {"subscribed": True}


@app.post("/push/send")
async def push_send(request: Request):
    """Send daily notification to all subscribers. Called by external cron."""
    secret = request.headers.get("x-push-secret", "")
    if not _PUSH_SECRET or secret != _PUSH_SECRET:
        raise HTTPException(status_code=403, detail="Forbidden")
    if not _VAPID_PRIVATE_KEY:
        raise HTTPException(status_code=500, detail="VAPID key not configured")

    day   = datetime.now(timezone.utc).weekday()   # 0=Mon … 6=Sun
    title, body = _DAILY_MESSAGES[day % len(_DAILY_MESSAGES)]

    result = supabase_admin.table("push_subscriptions").select("*").execute()
    subs   = result.data or []

    sent = failed = 0
    stale_endpoints: list[str] = []

    def _send_one(sub: dict) -> tuple[bool, bool]:
        from pywebpush import webpush, WebPushException
        try:
            webpush(
                subscription_info={
                    "endpoint": sub["endpoint"],
                    "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]},
                },
                data=_json.dumps({"title": title, "body": body, "url": "/"}),
                vapid_private_key=_VAPID_PRIVATE_KEY,
                vapid_claims=_VAPID_CLAIMS,
            )
            return True, False
        except WebPushException as exc:
            if exc.response and exc.response.status_code in (404, 410):
                return False, True   # stale subscription
            return False, False

    loop = asyncio.get_event_loop()
    futures = [loop.run_in_executor(_push_executor, _send_one, s) for s in subs]
    results = await asyncio.gather(*futures, return_exceptions=True)

    for sub, res in zip(subs, results):
        if isinstance(res, Exception):
            failed += 1
        elif res[0]:
            sent += 1
        else:
            failed += 1
            if res[1]:
                stale_endpoints.append(sub["endpoint"])

    # Clean up stale subscriptions
    for ep in stale_endpoints:
        supabase_admin.table("push_subscriptions").delete().eq("endpoint", ep).execute()

    return {"sent": sent, "failed": failed, "stale_removed": len(stale_endpoints)}


# ── Recipe URL Import ─────────────────────────────────────────────────────────
import re as _re
import html as _html_mod

class ImportRecipeRequest(BaseModel):
    url: str

def _strip_html_to_text(raw_html: str, max_chars: int = 18000) -> str:
    """Strip HTML tags, collapse whitespace, trim to max_chars for AI context."""
    # Remove script, style, nav, footer, header, aside blocks entirely
    cleaned = _re.sub(
        r'<(script|style|nav|footer|header|aside|noscript|svg)[^>]*>.*?</\1>',
        ' ', raw_html, flags=_re.DOTALL | _re.IGNORECASE
    )
    # Remove all remaining HTML tags
    cleaned = _re.sub(r'<[^>]+>', ' ', cleaned)
    # Decode HTML entities
    cleaned = _html_mod.unescape(cleaned)
    # Collapse runs of whitespace
    cleaned = _re.sub(r'\s{2,}', '\n', cleaned).strip()
    return cleaned[:max_chars]

def _extract_og_image(raw_html: str) -> str:
    """Pull og:image or first large <img> src from page HTML."""
    m = _re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', raw_html, _re.IGNORECASE)
    if not m:
        m = _re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']', raw_html, _re.IGNORECASE)
    if m:
        return m.group(1).strip()
    # Fallback: first img with a largish src
    imgs = _re.findall(r'<img[^>]+src=["\']([^"\']{20,})["\']', raw_html, _re.IGNORECASE)
    for img in imgs:
        if any(ext in img.lower() for ext in ['.jpg', '.jpeg', '.webp', '.png']):
            return img
    return ""

_IMPORT_SYSTEM = """You are a recipe extraction AI. Given raw webpage text, extract the recipe and return ONLY valid JSON — no markdown, no prose, nothing else.

Return this exact JSON shape (all fields required, use empty string/array/0 if data is missing):
{
  "name": "Recipe title",
  "cuisine": "e.g. Italian, Indian, Mexican",
  "time_minutes": 30,
  "servings": 4,
  "difficulty": "easy|medium|hard",
  "calories": 350,
  "description": "One sentence description",
  "ingredients_raw": ["1 cup flour", "2 tbsp butter", "3 eggs"],
  "steps": ["Step 1 text.", "Step 2 text."]
}

Rules:
- ingredients_raw: each element is ONE ingredient line with quantity+unit+name, e.g. "2 cups all-purpose flour"
- steps: each element is ONE complete step. Never break mid-sentence.
- difficulty: infer from time and technique (easy <30 min simple steps, hard >60 min or advanced)
- calories: per serving. Use 0 if not found.
- Return ONLY the JSON object. No explanation."""

async def _call_ai_for_import(text: str) -> str:
    """Call AI providers in order (Claude → Groq → Gemini) for recipe extraction."""
    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    groq_key      = os.getenv("GROQ_API_KEY", "").strip()
    gemini_key    = os.getenv("GEMINI_API_KEY", "").strip()

    user_msg = f"Extract the recipe from this webpage text:\n\n{text}"

    if anthropic_key:
        try:
            import anthropic as _anthropic
            client = _anthropic.Anthropic(api_key=anthropic_key)
            resp = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=1800,
                system=_IMPORT_SYSTEM,
                messages=[{"role": "user", "content": user_msg}],
            )
            return (resp.content[0].text or "").strip()
        except Exception:
            pass

    if groq_key:
        try:
            return await _call_groq(groq_key, _IMPORT_SYSTEM, [], user_msg)
        except Exception:
            pass

    if gemini_key:
        try:
            return await _call_gemini(gemini_key, _IMPORT_SYSTEM, [], user_msg)
        except Exception:
            pass

    raise HTTPException(status_code=503, detail="No AI provider available")

@app.post("/import-recipe")
async def import_recipe(payload: ImportRecipeRequest):
    """Fetch a recipe page URL and use AI to extract a structured recipe."""
    url = (payload.url or "").strip()

    # Basic validation
    if not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="URL must start with http:// or https://")
    blocked = ["localhost", "127.0.0.1", "0.0.0.0", "169.254.", "10.", "192.168.", "::1"]
    if any(b in url for b in blocked):
        raise HTTPException(status_code=400, detail="Private URLs are not allowed")

    # Fetch the page
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; SimmerBot/1.0; +https://mealskart.vercel.app)",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True, max_redirects=5) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code >= 400:
                raise HTTPException(status_code=422, detail=f"Could not fetch page (HTTP {resp.status_code})")
            raw_html = resp.text
    except httpx.TimeoutException:
        raise HTTPException(status_code=408, detail="Page took too long to load")
    except httpx.RequestError as e:
        raise HTTPException(status_code=422, detail=f"Could not reach URL: {str(e)[:120]}")

    # Extract OG image before stripping HTML
    image_url = _extract_og_image(raw_html)

    # Strip to plain text for AI
    page_text = _strip_html_to_text(raw_html)
    if len(page_text) < 100:
        raise HTTPException(status_code=422, detail="Page has too little readable text")

    # Call AI
    ai_raw = await _call_ai_for_import(page_text)

    # Parse AI JSON response
    try:
        json_str = ai_raw
        # Handle code-fenced responses
        m = _re.search(r'```(?:json)?\s*([\s\S]*?)```', json_str)
        if m:
            json_str = m.group(1)
        # Find first { ... } block
        m = _re.search(r'\{[\s\S]*\}', json_str)
        if not m:
            raise ValueError("No JSON object found")
        import json as _json
        data = _json.loads(m.group(0))
    except Exception:
        raise HTTPException(status_code=422, detail="AI could not parse a recipe from this page")

    # Validate minimum required fields
    if not data.get("name") or not data.get("steps"):
        raise HTTPException(status_code=422, detail="No recipe found on this page")

    # Parse ingredients_raw into structured format using the same logic as the frontend
    def _parse_ing(line: str):
        line = line.strip()
        if not line:
            return None
        m = _re.match(r'^(\d+(?:[./]\d+)?)\s*([a-z]+(?:\s[a-z]+)*)?\s+(.+)$', line, _re.IGNORECASE)
        if m:
            raw_qty = m.group(1)
            qty = eval(raw_qty) if '/' in raw_qty else float(raw_qty)  # noqa: S307
            return {"name": m.group(3).strip(), "quantity": round(qty, 3), "unit": (m.group(2) or "").lower().strip()}
        return {"name": line, "quantity": None, "unit": ""}

    ingredients_raw = data.get("ingredients_raw", [])
    parsed_ings = [p for p in (_parse_ing(l) for l in ingredients_raw) if p]

    # Build response in Simmer's recipe schema
    return {
        "name":        data.get("name", "Imported Recipe"),
        "cuisine":     data.get("cuisine", ""),
        "description": data.get("description", ""),
        "time_minutes": int(data.get("time_minutes") or 30),
        "servings":    int(data.get("servings") or 2),
        "difficulty":  data.get("difficulty", "easy"),
        "calories":    int(data.get("calories") or 0),
        "ingredients": [i["name"] for i in parsed_ings],
        "ingredients_with_quantities": parsed_ings,
        "ingredients_preview": [i["name"] for i in parsed_ings[:4]],
        "steps":       [s.strip() for s in data.get("steps", []) if str(s).strip()],
        "image_url":   image_url,
        "source_url":  url,
        "custom":      True,
    }


@app.post("/push/weekly-recap")
async def push_weekly_recap(request: Request):
    """Send weekly recap push every Sunday evening. Called by external cron."""
    secret = request.headers.get("x-push-secret", "")
    if not _PUSH_SECRET or secret != _PUSH_SECRET:
        raise HTTPException(status_code=403, detail="Forbidden")
    if not _VAPID_PRIVATE_KEY:
        raise HTTPException(status_code=500, detail="VAPID key not configured")

    # Pick a rotating weekly recap message
    week_num = datetime.now(timezone.utc).isocalendar()[1]
    weekly_messages = [
        ("📊 How was your week in the kitchen?", "See your cooking recap — streak, top dishes, and fresh picks for next week."),
        ("🔥 Weekly wrap-up is ready!", "Check your meals cooked, streak, and personalised picks for the week ahead."),
        ("🍳 Your week on Simmer", "Recipes cooked, streak update, and new ideas waiting for you."),
        ("🌟 End-of-week cooking recap", "Your personalised weekly summary is ready — tap to see how you did."),
    ]
    title, body = weekly_messages[week_num % len(weekly_messages)]

    result = supabase_admin.table("push_subscriptions").select("*").execute()
    subs = result.data or []

    sent = failed = 0
    stale_endpoints: list[str] = []

    def _send_weekly(sub: dict) -> tuple[bool, bool]:
        from pywebpush import webpush, WebPushException
        try:
            webpush(
                subscription_info={
                    "endpoint": sub["endpoint"],
                    "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]},
                },
                data=_json.dumps({"title": title, "body": body, "url": "/"}),
                vapid_private_key=_VAPID_PRIVATE_KEY,
                vapid_claims=_VAPID_CLAIMS,
            )
            return True, False
        except WebPushException as exc:
            if exc.response and exc.response.status_code in (404, 410):
                return False, True
            return False, False

    loop = asyncio.get_event_loop()
    futures = [loop.run_in_executor(_push_executor, _send_weekly, s) for s in subs]
    results = await asyncio.gather(*futures, return_exceptions=True)

    for sub, res in zip(subs, results):
        if isinstance(res, Exception):
            failed += 1
        elif res[0]:
            sent += 1
        else:
            failed += 1
            if res[1]:
                stale_endpoints.append(sub["endpoint"])

    for ep in stale_endpoints:
        supabase_admin.table("push_subscriptions").delete().eq("endpoint", ep).execute()

    return {"sent": sent, "failed": failed, "stale_removed": len(stale_endpoints), "message": title}
