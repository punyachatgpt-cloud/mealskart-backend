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


INDEX_PATH = Path(__file__).resolve().parent / "index.html"
interactions = []
recent_suggestions = []
user_preferences = {
    "quick": 0, "healthy": 0, "comfort": 0,
    "veg": 0, "non-veg": 0,
    # cuisine categories — boosted when user cooks from them
    "north-indian": 0, "south-indian": 0, "continental": 0,
    "chinese": 0, "snacks": 0, "sweets": 0, "drinks": 0, "salad": 0, "other": 0,
}


@app.on_event("startup")
async def load_recipes_on_startup():
    """
    Startup sequence:
      1. Load all recipes from Supabase (persistent — survives Render restarts).
      2. Seed CSV data if not already present (first deploy only).
      3. Kick off TheMealDB seeding as a background task — adds new recipes
         to Supabase and refreshes app.state.recipes when done.
    Falls back gracefully if TheMealDB is unreachable.
    """
    from seed_mealdb import seed_from_csv, seed_from_mealdb

    # Always upsert CSV rows so new additions (IDs 61-128) are picked up on each deploy
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
    target_category = _CATEGORY_KEYWORD_MAP.get(q_lower)
    target_diet     = _DIET_KEYWORD_MAP.get(q_lower)

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
    # Skip time filter when ingredients are present — ingredient matching is the primary
    # constraint, so we should not pre-eliminate recipes before the ingredient step.
    has_ingredients = bool(payload.ingredients)
    if not has_ingredients:
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

        # Personalization bonus: tags + diet + cuisine category learned from cook history
        preference_bonus = 0.0
        for tag in recipe.get("tags", []):
            preference_bonus += min(user_preferences.get(tag, 0), 10) * 0.5
        preference_bonus += min(user_preferences.get(recipe.get("diet", ""), 0), 10) * 0.5
        recipe_cat = (recipe.get("category") or "").strip().lower()
        preference_bonus += min(user_preferences.get(recipe_cat, 0), 10) * 0.4
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
                # Track cuisine category preference
                cat = (recipe.get("category") or "").strip().lower()
                if cat in user_preferences:
                    user_preferences[cat] += 1

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

Rules:
- Reply in 2-4 short sentences. Be specific and practical, never vague.
- If the user asks for recipe suggestions or ideas, end your reply with exactly:
  SUGGEST: <short search query>
  Example: SUGGEST: quick veg north indian dinner under 20 minutes
- Only add SUGGEST when they explicitly want recipe ideas. Never for technique/substitution questions.
- Do not repeat "SUGGEST:" more than once."""


def _parse_chef_reply(full_text: str) -> tuple[str, str]:
    recipe_query = ""
    if "SUGGEST:" in full_text:
        parts        = full_text.split("SUGGEST:", 1)
        full_text    = parts[0].strip()
        recipe_query = parts[1].strip().splitlines()[0].strip()
    return full_text, recipe_query


async def _call_gemini(api_key: str, system_prompt: str, messages: list[dict], user_msg: str) -> str:
    """Call Gemini via REST API with exponential backoff for 429 rate limits."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{_GEMINI_MODEL}:generateContent?key={api_key}"

    # Build Gemini contents array — interleave history then final user turn
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

    # Retry up to 4 times with exponential backoff on 429
    max_retries = 4
    backoff = 5  # seconds — doubles each retry: 5, 10, 20, 40
    async with httpx.AsyncClient(timeout=60.0) as client:
        for attempt in range(max_retries):
            resp = await client.post(url, json=body)
            if resp.status_code == 429:
                wait = backoff * (2 ** attempt)
                print(f"[Gemini] 429 rate-limited — retry {attempt + 1}/{max_retries} in {wait}s")
                if attempt < max_retries - 1:
                    await asyncio.sleep(wait)
                    continue
            resp.raise_for_status()
            data = resp.json()
            return data["candidates"][0]["content"]["parts"][0]["text"].strip()

    raise httpx.HTTPStatusError("Gemini rate limit exceeded after retries", request=resp.request, response=resp)


@app.post("/ai-chat")
async def ai_chef_chat(payload: AIChatRequest):
    """
    AI cooking assistant — supports Anthropic Claude (ANTHROPIC_API_KEY)
    or Google Gemini Flash (GEMINI_API_KEY) as a free alternative.
    Returns a natural-language reply and an optional recipe search query.
    """
    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    gemini_key    = os.getenv("GEMINI_API_KEY", "").strip()

    if not anthropic_key and not gemini_key:
        return {
            "reply": (
                "The AI Chef needs an API key to work. "
                "Add ANTHROPIC_API_KEY or GEMINI_API_KEY to your Render environment variables. "
                "Get a free Gemini key at aistudio.google.com/app/apikey — no credit card needed!"
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
        except Exception as exc:
            return {"reply": f"Oops, couldn't reach the AI Chef right now. ({exc})", "recipe_query": ""}

        reply, recipe_query = _parse_chef_reply(full_text)
        return {"reply": reply, "recipe_query": recipe_query}

    # ── Gemini path ───────────────────────────────────────────────────────────
    try:
        full_text = await _call_gemini(gemini_key, system_prompt, messages, payload.message.strip())
    except Exception as exc:
        return {"reply": f"Oops, couldn't reach the AI Chef right now. ({exc})", "recipe_query": ""}

    reply, recipe_query = _parse_chef_reply(full_text)
    return {"reply": reply, "recipe_query": recipe_query}


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
