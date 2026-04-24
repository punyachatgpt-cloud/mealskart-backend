import csv


CSV_FILE = "recipes.csv"
VALID_MOODS = {"quick", "healthy", "comfort"}
VALID_DIETS = {"veg", "non-veg"}


def load_recipes(filename):
    recipes = []

    with open(filename, newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        for row in reader:
            row["time_minutes"] = int(row["time_minutes"])
            row["tags"] = [tag.strip() for tag in row["tags"].split(",") if tag.strip()]
            recipes.append(row)

    return recipes


def get_time_available():
    while True:
        value = input("Enter time available in minutes: ").strip()
        try:
            return int(value)
        except ValueError:
            print("Please enter a valid integer.")


def get_choice(prompt, valid_values):
    while True:
        value = input(prompt).strip().lower()
        if value in valid_values:
            return value
        print(f"Please choose from: {', '.join(sorted(valid_values))}")


def score_recipe(recipe, time_available, mood, diet):
    score = 0
    reasons = []

    if recipe["diet"] == diet:
        score += 1
        reasons.append(f"matches your {diet} preference")

    if recipe["time_minutes"] <= time_available:
        score += 1
        reasons.append(f"fits your {time_available}-minute limit")

    if mood in recipe["tags"]:
        score += 1
        reasons.append(f"matches your {mood} mood")

    if "quick" in recipe["tags"] and time_available <= 15:
        score += 1
        reasons.append("gets an extra boost because it is quick for a short time window")

    return score, reasons


def rank_recipes(recipes, time_available, mood, diet):
    ranked = []

    for recipe in recipes:
        score, reasons = score_recipe(recipe, time_available, mood, diet)
        ranked.append(
            {
                "name": recipe["name"],
                "time_minutes": recipe["time_minutes"],
                "tags": ", ".join(recipe["tags"]),
                "score": score,
                "reasons": reasons,
            }
        )

    ranked.sort(key=lambda recipe: (-recipe["score"], recipe["time_minutes"], recipe["name"]))
    return ranked


def print_top_recipes(ranked_recipes):
    print("\nTop 3 recipes:\n")

    for recipe in ranked_recipes[:3]:
        print(f"Name: {recipe['name']}")
        print(f"Time: {recipe['time_minutes']} minutes")
        print(f"Tags: {recipe['tags']}")
        print(f"Score: {recipe['score']}")
        print("Why this dish:")

        if recipe["reasons"]:
            for reason in recipe["reasons"]:
                print(f"- {reason}")
        else:
            print("- No direct match, but it is still included in the best available options")

        print()


def main():
    recipes = load_recipes(CSV_FILE)

    time_available = get_time_available()
    mood = get_choice("Enter mood (quick, healthy, comfort): ", VALID_MOODS)
    diet = get_choice("Enter diet (veg, non-veg): ", VALID_DIETS)

    ranked_recipes = rank_recipes(recipes, time_available, mood, diet)
    print_top_recipes(ranked_recipes)


if __name__ == "__main__":
    main()
