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

# ── Method step templates (use {main}) ───────────────────────────────────────
METHODS = {
    "gravy": [
        "Heat oil and saute chopped onion, ginger and garlic until golden",
        "Add tomato puree and cook until the oil separates",
        "Stir in turmeric, red chilli, coriander and garam masala",
        "Add {main} with a little water and simmer until cooked through",
        "Finish with cream or coriander and serve hot",
    ],
    "dry": [
        "Heat oil and crackle cumin seeds",
        "Add {main} and saute on medium heat",
        "Sprinkle turmeric, red chilli, coriander powder and salt",
        "Cover and cook until tender, stirring occasionally",
        "Garnish with fresh coriander and serve",
    ],
    "dal": [
        "Pressure cook {main} with turmeric and salt until soft",
        "Prepare a tempering of ghee, cumin, garlic, dry chilli and asafoetida",
        "Pour the sizzling tempering over the dal",
        "Simmer for five minutes and adjust consistency",
        "Serve hot with rice or roti",
    ],
    "rice": [
        "Soak and parboil basmati rice with whole spices, then drain",
        "Cook a {main} masala with onion, tomato and yogurt",
        "Layer the rice over the masala and scatter fried onions and mint",
        "Cover and cook on dum on low heat for twenty minutes",
        "Fluff gently and serve with raita",
    ],
    "bread": [
        "Knead a soft dough with the flour, a little oil and water; rest 20 minutes",
        "Divide into balls and roll out, stuffing with {main} if required",
        "Cook on a hot tawa, brushing with ghee, until golden spots appear",
        "Serve warm with curd or curry",
    ],
    "tiffin": [
        "Soak rice and lentils, then grind to a smooth batter and ferment overnight",
        "Mix in {main} and season the batter",
        "Pour onto a hot greased griddle and spread or steam as needed",
        "Cook until golden and crisp (or fluffy)",
        "Serve hot with coconut chutney and sambar",
    ],
    "fry": [
        "Prepare the {main} mixture with spices and bind well",
        "Shape into portions or coat in batter",
        "Deep fry on medium heat until golden and crisp",
        "Drain on paper and serve hot with chutney",
    ],
    "chaat": [
        "Assemble the {main} base in a bowl",
        "Top with whisked yogurt, tamarind and green chutneys",
        "Sprinkle chaat masala, roasted cumin, sev and chopped onion",
        "Serve immediately while crisp",
    ],
    "milksweet": [
        "Cook {main} gently with milk and ghee on low heat",
        "Add sugar and cardamom and keep stirring",
        "Cook until thick and aromatic",
        "Garnish with chopped nuts and serve warm or chilled",
    ],
    "syrupsweet": [
        "Make a smooth batter or dough for the {main}",
        "Fry on low-medium heat until golden",
        "Soak in warm cardamom sugar syrup until plump",
        "Rest and serve",
    ],
    "drink": [
        "Add {main} to a blender with chilled water or milk",
        "Blend until smooth and frothy",
        "Sweeten or season to taste",
        "Pour over ice and serve chilled",
    ],
    "chai": [
        "Boil water with tea leaves, grated ginger and crushed spices",
        "Add milk and sugar",
        "Simmer to the strength you like",
        "Strain into cups and serve hot",
    ],
    "bake": [
        "Mix the batter (or knead and proof the dough) for the {main}",
        "Transfer to a greased tin or tray",
        "Bake at 180C until risen and golden",
        "Cool before slicing and serving",
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
        ("Paneer Bhurji", "crumbled paneer", "dry"), ("Egg Bhurji", "eggs", "dry"),
        ("Veg Kofta Curry", "vegetable dumplings", "gravy"), ("Mushroom Matar Masala", "mushroom and peas", "gravy"),
        ("Achari Aloo", "potato and pickle spices", "dry"), ("Sev Tamatar", "tomato and sev", "gravy"),
        ("Gatte Ki Sabzi", "gram flour dumplings", "gravy"), ("Ker Sangri", "desert beans and berries", "dry"),
        ("Undhiyu", "mixed winter vegetables", "gravy"), ("Litti Chokha", "stuffed wheat balls and mash", "bake")]:
    add(s, "veg", "north-indian", method, m, random.choice([25, 30, 35, 40]), random.choice([240, 300, 360]), "medium")

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
    # quick category breakdown
    from collections import Counter
    print(Counter(r["category"] for r in rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
