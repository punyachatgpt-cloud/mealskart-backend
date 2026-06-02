#!/usr/bin/env python3
"""
Generate a SQL file that inserts ~500 new recipes DIRECTLY into the Supabase
`recipes` Postgres table. Run this locally (no DB needed — it only writes a .sql
file), then run the produced SQL in the Supabase SQL editor.

The SQL is idempotent: it skips any recipe whose name already exists, auto-assigns
ids after the current MAX(id), sets source='csv' and image_url='' (the app's
image resolver fills the image automatically).

    python scripts/generate_recipes_sql.py        # writes supabase/seed_extra_recipes.sql
"""
from __future__ import annotations
import os
import random

random.seed(42)
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "supabase", "seed_extra_recipes.sql")
OUT_UPDATE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "supabase", "update_extra_recipe_steps.sql")

# ── Method step templates (use {main}) ───────────────────────────────────────
METHODS = {
    "gravy": [
        "Heat 2 tbsp oil in a heavy pan; add 1 large finely chopped onion and saute 5-6 minutes until golden brown",
        "Add 1 tbsp ginger-garlic paste and cook 1 minute until the raw smell disappears",
        "Add 2 pureed tomatoes (or 3 tbsp tomato paste) and cook 4-5 minutes until the oil separates at the edges",
        "Stir in 1/2 tsp turmeric, 1 tsp red chilli powder, 1 tsp coriander powder and 3/4 tsp salt; cook 1 minute",
        "Add the {main} with about 3/4 cup water, cover and simmer 10-12 minutes until cooked through and the gravy thickens",
        "Sprinkle 1/2 tsp garam masala, swirl in 2 tbsp cream or whisked yogurt, and finish with chopped coriander; serve hot",
    ],
    "dry": [
        "Heat 2 tbsp oil in a kadai on medium heat and crackle 1 tsp cumin seeds",
        "Add the {main} and saute on medium-high for 3-4 minutes",
        "Sprinkle 1/2 tsp turmeric, 1 tsp red chilli powder, 1.5 tsp coriander powder and 3/4 tsp salt; toss to coat evenly",
        "Cover and cook on low 8-10 minutes, stirring every couple of minutes, until tender and lightly caramelised",
        "Uncover and raise the heat for 2 minutes to dry off moisture",
        "Finish with 1/2 tsp garam masala and a handful of fresh coriander; serve hot",
    ],
    "dal": [
        "Rinse 1 cup {main} and pressure cook with 3 cups water, 1/2 tsp turmeric and 3/4 tsp salt for 3-4 whistles until soft",
        "Whisk the dal smooth and add hot water to reach a pourable consistency; keep on a low simmer",
        "For the tempering, heat 2 tbsp ghee and add 1 tsp cumin, 4 sliced garlic cloves, 2 dry red chillies and a pinch of asafoetida; fry until golden",
        "Pour the sizzling tempering over the dal",
        "Simmer 5 minutes, finish with chopped coriander and a squeeze of lemon; serve hot with rice or roti",
    ],
    "rice": [
        "Soak 1.5 cups basmati rice for 20 minutes; boil in 4-5 cups salted water with whole spices until 70% cooked, then drain",
        "In 2 tbsp ghee, cook a {main} masala with 1 sliced onion, 1 tbsp ginger-garlic, 2 chopped tomatoes, 1/2 cup yogurt and 1 tbsp biryani spices until thick",
        "Layer the par-boiled rice over the masala; scatter fried onions, mint, and 2 tbsp warm milk steeped with saffron",
        "Cover tightly (seal the lid with dough or foil) and cook on dum on the lowest heat 18-20 minutes",
        "Rest 5 minutes, then fluff gently with a fork and serve with raita",
    ],
    "bread": [
        "Knead a soft dough with 2 cups flour, 1/2 tsp salt, 1 tsp oil and about 3/4 cup water; cover and rest 20 minutes",
        "Divide into 6 balls; roll out, stuffing with {main} if required, and dust with dry flour",
        "Cook on a hot tawa 1-2 minutes per side, brushing with ghee, until golden brown spots appear and it puffs",
        "Serve warm with curd, pickle or curry",
    ],
    "tiffin": [
        "Soak 2 cups rice with 1/2 cup urad dal for 4-6 hours; grind to a smooth batter and ferment overnight",
        "Mix in the {main} with 3/4 tsp salt and a little water to a pourable (or idli) consistency",
        "Heat a greased griddle (or idli steamer); pour and spread thin, or steam 10-12 minutes",
        "Cook until golden and crisp, or fluffy and set",
        "Serve hot with coconut chutney and sambar",
    ],
    "fry": [
        "Mix the {main} with 1 finely chopped onion, 1 green chilli, 1/2 tsp turmeric, 1/2 tsp chilli powder and salt; bind well",
        "Shape into even portions, or dip in a thick gram-flour batter",
        "Heat oil to 170-180C and fry in small batches 3-4 minutes until golden and crisp",
        "Drain on paper towels; serve hot with green chutney",
    ],
    "chaat": [
        "Add the {main} base to a serving bowl",
        "Drizzle 2 tbsp whisked yogurt, 1 tbsp tamarind chutney and 1 tsp green chutney",
        "Sprinkle 1/2 tsp chaat masala, 1/4 tsp roasted cumin, a handful of sev and 2 tbsp chopped onion",
        "Finish with coriander and a squeeze of lemon; serve immediately while crisp",
    ],
    "milksweet": [
        "Cook the {main} with 2 cups full-fat milk and 1 tbsp ghee on low heat, stirring often so it doesn't catch",
        "When it thickens, add 1/2 cup sugar and 1/4 tsp cardamom powder; keep stirring 8-10 minutes",
        "Cook until it leaves the sides of the pan and turns glossy",
        "Garnish with 2 tbsp chopped nuts; serve warm or chilled",
    ],
    "syrupsweet": [
        "Make a smooth batter or dough for the {main} and rest 10 minutes",
        "Boil 1 cup sugar with 1/2 cup water, 2 cardamoms and a few saffron strands to a 1-string syrup; keep warm",
        "Fry on low-medium heat (about 160C) until evenly golden, turning often",
        "Soak the hot fritters in the warm syrup 15-20 minutes until plump",
        "Rest and serve",
    ],
    "drink": [
        "Add the {main} to a blender with 1 cup chilled water or milk",
        "Blend 30-40 seconds until smooth and frothy",
        "Add 2-3 tsp sugar to taste and blend again",
        "Pour over ice and serve chilled",
    ],
    "chai": [
        "Boil 1 cup water with 1 tsp tea leaves, 1 tsp grated ginger and 2 crushed cardamoms",
        "Add 3/4 cup milk and 2 tsp sugar",
        "Simmer 3-4 minutes to the strength you like",
        "Strain into cups and serve hot",
    ],
    "bake": [
        "Make the batter for the {main}: whisk 1.5 cups flour with 1 tsp baking powder, 1/2 cup sugar and the wet ingredients until smooth",
        "Pour or press into a greased tin lined with parchment",
        "Bake in a preheated 180C oven for 25-30 minutes until risen and a skewer comes out clean",
        "Cool 10 minutes before slicing and serving",
    ],
}

TAGS = {  # method -> default tag
    "gravy": "comfort", "dry": "healthy", "dal": "comfort", "rice": "comfort",
    "bread": "comfort", "tiffin": "healthy", "fry": "comfort", "chaat": "quick",
    "milksweet": "comfort", "syrupsweet": "comfort", "drink": "quick",
    "chai": "quick", "bake": "comfort",
}

BASE_SPICES = "onion, tomato, ginger, garlic, cumin, turmeric, red chilli powder, coriander powder, garam masala, salt, oil, coriander leaves"

# Method-appropriate base ingredients (so sweets/drinks/bakery don't get onion & chilli).
METHOD_BASE = {
    "gravy":      BASE_SPICES,
    "dry":        BASE_SPICES,
    "fry":        "gram flour, rice flour, green chilli, ginger, turmeric, salt, oil, coriander leaves",
    "dal":        "ghee, cumin, garlic, dry red chilli, asafoetida, turmeric, salt, coriander leaves",
    "rice":       "basmati rice, whole spices, onion, yogurt, salt, ghee, mint, coriander leaves",
    "bread":      "whole wheat flour, salt, oil, ghee, water",
    "tiffin":     "rice, urad dal, salt, oil, mustard seeds, curry leaves",
    "chaat":      "chaat masala, tamarind chutney, mint chutney, yogurt, sev, onion, coriander leaves, roasted cumin",
    "milksweet":  "sugar, milk, ghee, cardamom, chopped nuts",
    "syrupsweet": "sugar, ghee, cardamom, saffron, water",
    "drink":      "sugar, chilled water, ice",
    "chai":       "milk, sugar, water",
    "bake":       "refined flour, sugar, butter, baking powder, vanilla, salt",
}

rows: list[dict] = []
seen: set[str] = set()

def add(name, diet, category, method, main, time, cal, diff, extra_ing=""):
    key = name.strip().lower()
    if key in seen:
        return
    seen.add(key)
    ing = ", ".join(filter(None, [main, extra_ing, METHOD_BASE.get(method, BASE_SPICES)]))
    steps = "; ".join(s.replace("{main}", main or name) for s in METHODS[method])
    rows.append({
        "name": name.strip(), "diet": diet, "category": category,
        "time": time, "cal": cal, "diff": diff, "tags": TAGS[method],
        "ingredients": ing, "steps": steps,
    })

# ── Combinatorial mains × styles ─────────────────────────────────────────────
VEG_MAINS = {
    "Paneer": "paneer", "Aloo": "potato", "Gobi": "cauliflower", "Bhindi": "okra",
    "Baingan": "brinjal", "Matar": "green peas", "Mushroom": "mushroom",
    "Chana": "chickpeas", "Rajma": "kidney beans", "Lauki": "bottle gourd",
    "Tinda": "tinda", "Kaddu": "pumpkin", "Methi": "fenugreek leaves",
    "Palak": "spinach", "Soya Chunk": "soya chunks", "Mixed Veg": "mixed vegetables",
}
GRAVY_STYLES = ["Butter Masala", "Tikka Masala", "Kadai", "Korma", "Do Pyaza",
                "Lababdar", "Masala", "Curry", "Handi", "Kofta"]
DRY_STYLES = ["Fry", "Jeera", "Sukha", "Roast", "Bhujia"]

for base, main in VEG_MAINS.items():
    for style in random.sample(GRAVY_STYLES, 4):
        t = random.choice([25, 30, 35, 40]); c = random.choice([260, 300, 340, 380])
        add(f"{base} {style}", "veg", "north-indian", "gravy", main, t, c,
            "medium" if t >= 35 else "easy")
    for style in random.sample(DRY_STYLES, 3):
        t = random.choice([18, 22, 25]); c = random.choice([180, 220, 260])
        add(f"{base} {style}", "veg", "north-indian", "dry", main, t, c, "easy")

NONVEG_MAINS = {"Chicken": "chicken", "Mutton": "mutton", "Egg": "boiled eggs",
                "Fish": "fish", "Prawn": "prawns"}
NV_STYLES = ["Curry", "Masala", "Kadai", "Korma", "Do Pyaza", "Tikka Masala",
             "Chettinad", "Bhuna", "Rogan Josh", "Vindaloo", "65", "Manchurian"]
for base, main in NONVEG_MAINS.items():
    for style in random.sample(NV_STYLES, 9):
        t = random.choice([35, 40, 45, 50]); c = random.choice([320, 380, 420, 460])
        add(f"{base} {style}", "non-veg", "north-indian", "gravy", main, t, c, "medium")

# Dals
for d, ing in {"Dal Tadka": "toor dal", "Dal Fry": "toor dal", "Dal Makhani": "black lentils and kidney beans",
               "Panchmel Dal": "five mixed lentils", "Moong Dal": "yellow moong dal",
               "Masoor Dal": "red lentils", "Chana Dal": "split chickpea lentils",
               "Lobia Curry": "black-eyed peas", "Dal Palak": "lentils and spinach",
               "Dal Dhokli": "lentils and wheat dumplings", "Sambar Dal": "toor dal and vegetables",
               "Kali Dal": "whole urad dal", "Mixed Dal": "assorted lentils"}.items():
    add(d, "veg", "north-indian", "dal", ing, random.choice([30, 35, 40]), random.choice([210, 240, 280]), "easy")

# Breads
for b, m in {"Aloo Paratha": "spiced mashed potato", "Gobi Paratha": "grated cauliflower",
             "Paneer Paratha": "crumbled paneer", "Methi Paratha": "fenugreek leaves",
             "Pyaaz Paratha": "spiced onion", "Mooli Paratha": "grated radish",
             "Lachha Paratha": "", "Tandoori Roti": "", "Butter Naan": "",
             "Garlic Naan": "garlic and coriander", "Missi Roti": "gram flour",
             "Bhatura": "", "Puri": "", "Stuffed Kulcha": "spiced potato"}.items():
    add(b, "veg", "north-indian", "bread", m, random.choice([20, 25, 30]), random.choice([180, 220, 260]),
        "medium" if "Naan" in b or "Bhatura" in b else "easy")

# Rice / biryani
for r, m, diet in [("Veg Biryani", "mixed vegetables", "veg"), ("Paneer Biryani", "paneer", "veg"),
                   ("Chicken Biryani", "chicken", "non-veg"), ("Mutton Biryani", "mutton", "non-veg"),
                   ("Egg Biryani", "boiled eggs", "non-veg"), ("Hyderabadi Biryani", "chicken", "non-veg"),
                   ("Veg Pulao", "mixed vegetables", "veg"), ("Peas Pulao", "green peas", "veg"),
                   ("Jeera Rice", "cumin", "veg"), ("Kashmiri Pulao", "nuts and fruit", "veg"),
                   ("Tawa Pulao", "mixed vegetables", "veg"), ("Curd Rice", "yogurt", "veg"),
                   ("Lemon Rice", "lemon and peanuts", "veg"), ("Tomato Rice", "tomato", "veg"),
                   ("Coconut Rice", "fresh coconut", "veg"), ("Bisi Bele Bath", "lentils and vegetables", "veg"),
                   ("Tamarind Rice", "tamarind", "veg"), ("Vegetable Fried Rice", "mixed vegetables", "veg")]:
    cat = "south-indian" if r in ("Curd Rice", "Lemon Rice", "Coconut Rice", "Bisi Bele Bath", "Tamarind Rice", "Tomato Rice") else "north-indian"
    add(r, diet, cat, "rice", m, random.choice([35, 40, 45]), random.choice([320, 360, 400]),
        "medium" if "Biryani" in r else "easy")

# South Indian tiffin
for s, m in {"Plain Dosa": "", "Masala Dosa": "spiced potato", "Onion Dosa": "onion",
             "Rava Dosa": "semolina", "Set Dosa": "", "Mysore Masala Dosa": "red chutney and potato",
             "Paper Dosa": "", "Ghee Roast Dosa": "ghee", "Idli": "", "Rava Idli": "semolina",
             "Medu Vada": "urad dal", "Sambar Vada": "lentil and sambar", "Dahi Vada": "yogurt",
             "Uttapam": "onion and tomato", "Pongal": "rice and moong dal", "Upma": "semolina",
             "Rava Kesari": "semolina", "Pesarattu": "green gram", "Appam": "rice and coconut",
             "Idiyappam": "rice flour"}.items():
    method = "milksweet" if s == "Rava Kesari" else ("fry" if "Vada" in s else "tiffin")
    cat = "sweets" if s == "Rava Kesari" else "south-indian"
    add(s, "veg", cat, method, m, random.choice([20, 25, 30]), random.choice([200, 240, 280]), "easy")

# South curries
for s, m in {"Sambar": "lentils and vegetables", "Rasam": "tamarind and tomato",
             "Tomato Rasam": "tomato", "Pepper Rasam": "black pepper", "Avial": "mixed vegetables and coconut",
             "Vegetable Korma": "mixed vegetables and coconut", "Kara Kuzhambu": "vegetables and tamarind",
             "Poriyal": "beans and coconut", "Kootu": "lentils and vegetables", "Olan": "ash gourd and coconut",
             "Theeyal": "shallots and roasted coconut"}.items():
    add(s, "veg", "south-indian", "gravy" if "Rasam" not in s and "Sambar" not in s else "dal",
        m, random.choice([25, 30, 35]), random.choice([180, 220, 260]), "easy")

# Snacks / street food
for s, m, method in [("Samosa", "spiced potato and peas", "fry"), ("Onion Pakora", "onion", "fry"),
        ("Aloo Pakora", "potato", "fry"), ("Paneer Pakora", "paneer", "fry"), ("Bread Pakora", "bread and potato", "fry"),
        ("Mirchi Bajji", "green chilli", "fry"), ("Vegetable Cutlet", "mixed vegetables", "fry"),
        ("Aloo Tikki", "potato", "fry"), ("Hara Bhara Kabab", "spinach and peas", "fry"),
        ("Veg Spring Roll", "shredded vegetables", "fry"), ("Veg Momos", "cabbage and carrot", "tiffin"),
        ("Paneer Momos", "paneer", "tiffin"), ("Dhokla", "gram flour", "tiffin"), ("Khaman", "gram flour", "tiffin"),
        ("Khandvi", "gram flour and yogurt", "tiffin"), ("Handvo", "lentils and bottle gourd", "bake"),
        ("Kachori", "spiced lentils", "fry"), ("Pyaaz Kachori", "spiced onion", "fry"),
        ("Vada Pav", "potato fritter and bun", "fry"), ("Pav Bhaji", "mashed mixed vegetables", "gravy"),
        ("Misal Pav", "sprouts curry and bun", "gravy"), ("Dabeli", "potato and bun", "chaat"),
        ("Pani Puri", "puri, potato and spiced water", "chaat"), ("Bhel Puri", "puffed rice", "chaat"),
        ("Sev Puri", "puri, potato and sev", "chaat"), ("Dahi Puri", "puri, potato and yogurt", "chaat"),
        ("Aloo Chaat", "fried potato", "chaat"), ("Papdi Chaat", "papdi, potato and yogurt", "chaat"),
        ("Ragda Pattice", "potato patties and white peas", "chaat"), ("Chana Chaat", "chickpeas", "chaat"),
        ("Corn Chaat", "sweet corn", "chaat"), ("Fruit Chaat", "mixed fruit", "chaat"),
        ("Veg Frankie", "vegetables and roti", "fry"), ("Veg Sandwich", "vegetables and bread", "chaat"),
        ("Grilled Cheese Sandwich", "cheese and bread", "bake"), ("Maggi Masala", "noodles and vegetables", "dry"),
        ("Masala Papad", "papad", "chaat"), ("Sabudana Vada", "sago and potato", "fry"),
        ("Batata Vada", "potato", "fry"), ("Mysore Bonda", "flour", "fry"), ("Bonda", "potato", "fry"),
        ("Cheese Balls", "cheese and potato", "fry"), ("French Fries Masala", "potato", "fry")]:
    add(s, "veg", "snacks", method, m, random.choice([15, 20, 25, 30]), random.choice([180, 240, 300]),
        "easy" if method in ("chaat", "dry") else "medium")

# Indo-Chinese
for s, m, diet in [("Veg Manchurian", "mixed vegetables", "veg"), ("Gobi Manchurian", "cauliflower", "veg"),
        ("Paneer Chilli", "paneer", "veg"), ("Veg Hakka Noodles", "noodles and vegetables", "veg"),
        ("Veg Fried Rice", "rice and vegetables", "veg"), ("Schezwan Noodles", "noodles", "veg"),
        ("Chilli Potato", "potato", "veg"), ("Spring Onion Rice", "rice and spring onion", "veg"),
        ("Chicken Manchurian", "chicken", "non-veg"), ("Chilli Chicken", "chicken", "non-veg"),
        ("Chicken Fried Rice", "rice and chicken", "non-veg"), ("Chicken Hakka Noodles", "noodles and chicken", "non-veg"),
        ("Chicken Lollipop", "chicken", "non-veg"), ("Egg Fried Rice", "rice and egg", "non-veg")]:
    method = "dry" if ("Chilli" in s or "Manchurian" in s) else ("rice" if "Rice" in s else "dry")
    add(s, diet, "chinese", method, m, random.choice([25, 30, 35]), random.choice([300, 360, 420]), "medium")

# Sweets / mithai
for s, m, method in [("Gulab Jamun", "milk solids", "syrupsweet"), ("Jalebi", "fermented batter", "syrupsweet"),
        ("Rasgulla", "chhena", "syrupsweet"), ("Rasmalai", "chhena and milk", "milksweet"),
        ("Gajar Halwa", "grated carrot", "milksweet"), ("Suji Halwa", "semolina", "milksweet"),
        ("Moong Dal Halwa", "moong dal", "milksweet"), ("Besan Halwa", "gram flour", "milksweet"),
        ("Atte Ka Halwa", "wheat flour", "milksweet"), ("Lauki Halwa", "bottle gourd", "milksweet"),
        ("Rice Kheer", "rice and milk", "milksweet"), ("Sevai Kheer", "vermicelli and milk", "milksweet"),
        ("Sabudana Kheer", "sago and milk", "milksweet"), ("Makhana Kheer", "fox nuts and milk", "milksweet"),
        ("Besan Ladoo", "gram flour", "milksweet"), ("Motichoor Ladoo", "gram flour pearls", "syrupsweet"),
        ("Coconut Ladoo", "coconut and milk", "milksweet"), ("Rava Ladoo", "semolina", "milksweet"),
        ("Boondi Ladoo", "gram flour boondi", "syrupsweet"), ("Til Ladoo", "sesame and jaggery", "milksweet"),
        ("Kaju Katli", "cashew", "milksweet"), ("Besan Barfi", "gram flour", "milksweet"),
        ("Coconut Barfi", "coconut", "milksweet"), ("Milk Barfi", "milk solids", "milksweet"),
        ("Chocolate Barfi", "milk solids and cocoa", "milksweet"), ("Mysore Pak", "gram flour and ghee", "milksweet"),
        ("Sandesh", "chhena", "milksweet"), ("Peda", "milk solids", "milksweet"),
        ("Malpua", "flour and milk", "syrupsweet"), ("Imarti", "urad dal batter", "syrupsweet"),
        ("Balushahi", "flour", "syrupsweet"), ("Shahi Tukda", "fried bread and milk", "milksweet"),
        ("Phirni", "ground rice and milk", "milksweet"), ("Basundi", "thickened milk", "milksweet"),
        ("Shrikhand", "hung yogurt", "milksweet"), ("Modak", "rice flour and coconut", "tiffin"),
        ("Puran Poli", "lentil and jaggery", "bread"), ("Gajak", "sesame and jaggery", "milksweet"),
        ("Gond Ladoo", "edible gum and flour", "milksweet"), ("Anjeer Barfi", "fig and nuts", "milksweet")]:
    cat = "sweets"
    add(s, "veg", cat, method, m, random.choice([30, 40, 50]), random.choice([280, 340, 400]),
        "medium")

# Drinks
for s, m, method in [("Sweet Lassi", "yogurt", "drink"), ("Salted Lassi", "yogurt", "drink"),
        ("Mango Lassi", "mango and yogurt", "drink"), ("Rose Lassi", "rose and yogurt", "drink"),
        ("Strawberry Lassi", "strawberry and yogurt", "drink"), ("Masala Chaas", "buttermilk", "drink"),
        ("Masala Chai", "tea and spices", "chai"), ("Ginger Chai", "tea and ginger", "chai"),
        ("Cardamom Chai", "tea and cardamom", "chai"), ("Tulsi Chai", "tea and holy basil", "chai"),
        ("Kashmiri Kahwa", "green tea, saffron and nuts", "chai"), ("Filter Coffee", "coffee and milk", "chai"),
        ("Cold Coffee", "coffee and milk", "drink"), ("Aam Panna", "raw mango", "drink"),
        ("Jaljeera", "cumin and mint", "drink"), ("Nimbu Pani", "lemon", "drink"),
        ("Rooh Afza Sharbat", "rose syrup and milk", "drink"), ("Thandai", "nuts, milk and spices", "drink"),
        ("Badam Milk", "almond and milk", "drink"), ("Kesar Milk", "saffron and milk", "drink"),
        ("Banana Shake", "banana and milk", "drink"), ("Mango Shake", "mango and milk", "drink"),
        ("Chikoo Shake", "sapota and milk", "drink"), ("Oreo Shake", "biscuits and milk", "drink"),
        ("Mango Smoothie", "mango and yogurt", "drink"), ("Mixed Fruit Smoothie", "mixed fruit", "drink"),
        ("Watermelon Juice", "watermelon", "drink"), ("Orange Juice", "orange", "drink"),
        ("Sugarcane Juice", "sugarcane", "drink"), ("Coconut Water", "tender coconut", "drink"),
        ("Beetroot Juice", "beetroot", "drink"), ("Sol Kadhi", "kokum and coconut", "drink"),
        ("Falooda", "vermicelli, rose and milk", "drink"), ("Bael Sharbat", "wood apple", "drink"),
        ("Sattu Sharbat", "roasted gram flour", "drink"), ("Lemon Iced Tea", "tea and lemon", "drink")]:
    add(s, "veg", "drinks", method, m, random.choice([5, 8, 10, 12]), random.choice([90, 140, 180, 220]), "easy")

# Bakery
for s, m, cat in [("Vanilla Sponge Cake", "flour, sugar and butter", "sweets"),
        ("Chocolate Cake", "flour, cocoa and sugar", "sweets"), ("Eggless Vanilla Cake", "flour and condensed milk", "sweets"),
        ("Banana Bread", "banana and flour", "sweets"), ("Marble Cake", "flour, cocoa and butter", "sweets"),
        ("Pineapple Pastry", "sponge and pineapple", "sweets"), ("Black Forest Pastry", "chocolate sponge and cream", "sweets"),
        ("Carrot Cake", "carrot and flour", "sweets"), ("Mawa Cake", "milk solids and flour", "sweets"),
        ("Tutti Frutti Cake", "flour and candied fruit", "sweets"), ("Nankhatai", "flour, ghee and sugar", "sweets"),
        ("Coconut Cookies", "coconut and flour", "sweets"), ("Jeera Biscuits", "flour and cumin", "snacks"),
        ("Butter Cookies", "butter and flour", "sweets"), ("Chocolate Chip Cookies", "flour and chocolate chips", "sweets"),
        ("Atta Biscuits", "wheat flour and jaggery", "sweets"), ("Rusk Toast", "bread", "sweets"),
        ("Khari Biscuit", "puff pastry", "snacks"), ("Veg Puff", "spiced vegetables and pastry", "snacks"),
        ("Paneer Puff", "paneer and pastry", "snacks"), ("Egg Puff", "egg and pastry", "snacks"),
        ("Dilkhush", "sweet bun with coconut", "sweets"), ("Bun Maska", "soft bun and butter", "snacks"),
        ("Cream Roll", "pastry and cream", "sweets"), ("Garlic Bread", "bread and garlic butter", "snacks"),
        ("Cheese Garlic Bread", "bread, cheese and garlic", "snacks"), ("Pav Buns", "soft bread rolls", "snacks"),
        ("Whole Wheat Bread", "wheat flour and yeast", "snacks"), ("Focaccia", "flour, yeast and herbs", "continental"),
        ("Pizza Margherita", "flour, tomato and cheese", "continental"), ("Veg Pizza", "flour, vegetables and cheese", "continental"),
        ("Quiche", "eggs, cream and pastry", "continental"), ("Brownie", "chocolate, butter and flour", "sweets"),
        ("Muffins", "flour, sugar and milk", "sweets"), ("Doughnut", "flour, sugar and yeast", "sweets"),
        ("Cinnamon Roll", "flour, cinnamon and sugar", "sweets"), ("Croissant", "laminated butter dough", "continental"),
        ("Apple Pie", "apple and pastry", "sweets"), ("Custard Tart", "egg custard and pastry", "sweets")]:
    diet = "non-veg" if ("Egg" in s or "Quiche" in s) and "Eggless" not in s else "veg"
    add(s, diet, cat, "bake", m, random.choice([40, 45, 50, 60]), random.choice([280, 340, 420, 480]), "medium")


# ── Extra curated standalone dishes ──────────────────────────────────────────
for s, m, method in [("Shahi Paneer", "paneer and cashew", "gravy"), ("Malai Kofta", "paneer and potato dumplings", "gravy"),
        ("Navratan Korma", "nine vegetables and nuts", "gravy"), ("Veg Kolhapuri", "mixed vegetables", "gravy"),
        ("Baingan Bharta", "smoked aubergine", "dry"), ("Sarson Ka Saag", "mustard greens", "gravy"),
        ("Dum Aloo", "baby potatoes", "gravy"), ("Aloo Gobi", "potato and cauliflower", "dry"),
        ("Aloo Matar", "potato and peas", "gravy"), ("Bhindi Masala", "okra", "dry"),
        ("Chole Masala", "chickpeas", "gravy"), ("Pindi Chole", "chickpeas", "gravy"),
        ("Kadhi Pakora", "yogurt and gram flour fritters", "gravy"), ("Veg Jalfrezi", "mixed vegetables", "dry"),
        ("Stuffed Capsicum", "bell peppers and potato", "dry"), ("Methi Malai Matar", "fenugreek, cream and peas", "gravy"),
        ("Paneer Bhurji", "crumbled paneer", "dry"),
        ("Veg Kofta Curry", "vegetable dumplings", "gravy"), ("Mushroom Matar Masala", "mushroom and peas", "gravy"),
        ("Achari Aloo", "potato and pickle spices", "dry"), ("Sev Tamatar", "tomato and sev", "gravy"),
        ("Gatte Ki Sabzi", "gram flour dumplings", "gravy"), ("Ker Sangri", "desert beans and berries", "dry"),
        ("Undhiyu", "mixed winter vegetables", "gravy"), ("Litti Chokha", "stuffed wheat balls and mash", "bake")]:
    add(s, "veg", "north-indian", method, m, random.choice([25, 30, 35, 40]), random.choice([240, 300, 360]), "medium")

# Egg dishes are non-veg (egg is not vegetarian in this app's diet model).
add("Egg Bhurji", "non-veg", "north-indian", "dry", "eggs", 20, 280, "easy")

for s, m, method in [("Kerala Parotta", "refined flour", "bread"), ("Malabar Parotta", "refined flour", "bread"),
        ("Vegetable Stew", "mixed vegetables and coconut milk", "gravy"), ("Puttu", "rice flour and coconut", "tiffin"),
        ("Ven Pongal", "rice and moong dal", "tiffin"), ("Kara Pongal", "rice, dal and pepper", "tiffin"),
        ("Lemon Sevai", "rice noodles and lemon", "tiffin"), ("Coconut Sevai", "rice noodles and coconut", "tiffin"),
        ("Chettinad Vegetable Curry", "mixed vegetables", "gravy"), ("Kadala Curry", "black chickpeas and coconut", "gravy"),
        ("Mor Kuzhambu", "yogurt and vegetables", "gravy"), ("Vendakai Poriyal", "okra and coconut", "dry"),
        ("Cabbage Thoran", "cabbage and coconut", "dry"), ("Beans Poriyal", "green beans and coconut", "dry")]:
    add(s, "veg", "south-indian", method, m, random.choice([20, 25, 30, 35]), random.choice([200, 250, 300]), "easy")

for s, m, method in [("Sabudana Khichdi", "sago and peanuts", "dry"), ("Murukku", "rice and gram flour", "fry"),
        ("Chakli", "rice flour", "fry"), ("Mathri", "refined flour", "fry"), ("Namak Para", "refined flour", "fry"),
        ("Shankarpali", "flour and sugar", "fry"), ("Banana Chips", "raw banana", "fry"), ("Maddur Vada", "rice and semolina", "fry"),
        ("Masala Vada", "chana dal", "fry"), ("Aloo Bonda", "potato", "fry"), ("Mangode", "moong dal", "fry"),
        ("Cheese Corn Balls", "corn and cheese", "fry"), ("Veg Manchurian Dry", "mixed vegetables", "dry"),
        ("Tandoori Momos", "vegetables", "dry"), ("Chilli Paneer Dry", "paneer", "dry"), ("Honey Chilli Potato", "potato", "dry"),
        ("Aloo Bhujia", "potato and gram flour", "fry"), ("Poha Chivda", "flattened rice", "dry"),
        ("Masala Peanuts", "peanuts and gram flour", "fry"), ("Corn Bhel", "sweet corn", "chaat")]:
    add(s, "veg", "snacks", method, m, random.choice([15, 20, 25]), random.choice([180, 240, 300]), "easy")

for s, m in {"Kalakand": "milk and paneer", "Soan Papdi": "gram flour and ghee", "Ghevar": "flour and syrup",
        "Petha": "ash gourd", "Chikki": "peanuts and jaggery", "Patisa": "gram flour",
        "Doodh Peda": "milk solids", "Kaju Roll": "cashew", "Dryfruit Laddu": "dates and nuts",
        "Churma Ladoo": "wheat and jaggery", "Coconut Burfi": "coconut", "Badam Halwa": "almond",
        "Pineapple Sheera": "semolina and pineapple", "Apple Kheer": "apple and milk", "Carrot Kheer": "carrot and milk",
        "Thekua": "wheat and jaggery", "Til Chikki": "sesame and jaggery", "Rajbhog": "chhena and saffron"}.items():
    method = "syrupsweet" if s in ("Ghevar", "Rajbhog") else "milksweet"
    add(s, "veg", "sweets", method, m, random.choice([35, 45, 55]), random.choice([300, 360, 420]), "medium")

for s, m in {"Spiced Buttermilk": "buttermilk and spices", "Lemon Soda": "lemon and soda", "Masala Soda": "soda and spices",
        "Kokum Sharbat": "kokum", "Ragi Malt": "finger millet and milk", "Turmeric Latte": "turmeric and milk",
        "Hot Chocolate": "cocoa and milk", "Green Smoothie": "spinach and banana", "Pineapple Juice": "pineapple",
        "Pomegranate Juice": "pomegranate", "Mosambi Juice": "sweet lime", "Carrot Ginger Juice": "carrot and ginger"}.items():
    add(s, "veg", "drinks", "drink", m, random.choice([5, 8, 10]), random.choice([90, 130, 170]), "easy")

for s, m, cat in [("Atta Cake", "wheat flour and jaggery", "sweets"), ("Coconut Macaroon", "coconut", "sweets"),
        ("Honey Cake", "sponge and honey", "sweets"), ("Walnut Brownie", "chocolate and walnut", "sweets"),
        ("Swiss Roll", "sponge and jam", "sweets"), ("Fruit Cake", "flour and dried fruit", "sweets"),
        ("Cheese Straws", "cheese and pastry", "snacks"), ("Masala Bun", "spiced bread roll", "snacks"),
        ("Stuffed Bread Roll", "potato and bread", "snacks"), ("Pita Bread", "flour and yeast", "continental")]:
    diet = "veg"
    add(s, diet, cat, "bake", m, random.choice([40, 50, 60]), random.choice([300, 380, 450]), "medium")


def esc(s: str) -> str:
    return str(s).replace("'", "''")


def main() -> int:
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    lines = []
    lines.append("-- Auto-generated: inserts new recipes into public.recipes.")
    lines.append("-- Idempotent: skips names that already exist; ids continue after MAX(id).")
    lines.append("-- image_url left blank — the app's image resolver fills it automatically.")
    lines.append("-- Run this in the Supabase SQL editor.\n")
    lines.append("with new_recipes (name, ingredients, time_minutes, calories, difficulty, diet, tags, category, steps) as (")
    lines.append("  values")
    vals = []
    for r in rows:
        vals.append(
            f"    ('{esc(r['name'])}', '{esc(r['ingredients'])}', {r['time']}, {r['cal']}, "
            f"'{r['diff']}', '{r['diet']}', '{esc(r['tags'])}', '{r['category']}', '{esc(r['steps'])}')"
        )
    lines.append(",\n".join(vals))
    lines.append(")")
    lines.append("insert into public.recipes (id, name, ingredients, time_minutes, calories, difficulty, diet, tags, category, steps, image_url, source, external_id)")
    lines.append("select")
    lines.append("  (select coalesce(max(id), 0) from public.recipes) + row_number() over (order by n.name),")
    lines.append("  n.name, n.ingredients, n.time_minutes, n.calories, n.difficulty, n.diet, n.tags, n.category, n.steps,")
    lines.append("  '', 'csv', ''")
    lines.append("from new_recipes n")
    lines.append("where not exists (select 1 from public.recipes r where lower(r.name) = lower(n.name));")
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"Wrote {len(rows)} recipes to {OUT}")

    # ── Companion UPDATE: refresh steps + ingredients on rows that already exist ──
    # (the INSERT above skips existing names, so run this to upgrade recipes that
    #  were seeded before the detailed-step rewrite). Matches by name, only touches
    #  these generated recipes.
    up = []
    up.append("-- Auto-generated: upgrades steps + ingredients for the curated recipes")
    up.append("-- already in public.recipes (the seed INSERT skips existing names).")
    up.append("-- Safe to re-run; only updates rows whose name matches. Run in Supabase SQL editor.\n")
    up.append("update public.recipes r")
    up.append("set steps = v.steps, ingredients = v.ingredients")
    up.append("from (values")
    uvals = [f"    ('{esc(r['name'])}', '{esc(r['steps'])}', '{esc(r['ingredients'])}')" for r in rows]
    up.append(",\n".join(uvals))
    up.append(") as v(name, steps, ingredients)")
    up.append("where lower(r.name) = lower(v.name);")
    with open(OUT_UPDATE, "w", encoding="utf-8") as f:
        f.write("\n".join(up) + "\n")
    print(f"Wrote UPDATE for {len(rows)} recipes to {OUT_UPDATE}")
    # quick category breakdown
    from collections import Counter
    print(Counter(r["category"] for r in rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
