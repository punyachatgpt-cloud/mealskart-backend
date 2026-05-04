import sys
import unittest

sys.dont_write_bytecode = True

from fastapi.testclient import TestClient

import fastapi_app


class MealsKartApiContractTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(fastapi_app.app)
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)

    def test_recommendations_include_nutrition_and_recipe_summary(self):
        response = self.client.post(
            "/recommend",
            json={
                "time_available": 15,
                "mood": "quick",
                "diet": "veg",
                "mode": "normal",
                "ingredients": ["poha", "onion"],
                "category": "north-indian",
            },
        )

        self.assertEqual(response.status_code, 200)
        item = response.json()[0]

        self.assertIsInstance(item["calories"], int)
        self.assertEqual(item["difficulty"], "easy")
        self.assertGreaterEqual(item["ingredient_match_percent"], 0)
        self.assertLessEqual(item["ingredient_match_percent"], 100)
        self.assertIn("ingredients_preview", item)
        self.assertGreater(len(item["ingredients_preview"]), 0)

    def test_recipe_detail_includes_ingredients_and_nutrition(self):
        response = self.client.get("/recipe/1")

        self.assertEqual(response.status_code, 200)
        recipe = response.json()

        self.assertEqual(recipe["name"], "Poha")
        self.assertEqual(recipe["calories"], 280)
        self.assertEqual(recipe["difficulty"], "easy")
        self.assertEqual(recipe["time_minutes"], 14)
        self.assertIn("poha", recipe["ingredients"])
        self.assertGreater(len(recipe["steps"]), 0)

    def test_meal_plan_returns_days_and_grocery_list(self):
        response = self.client.post(
            "/meal-plan",
            json={
                "days": 3,
                "meals_per_day": 2,
                "time_available": 30,
                "diet": "veg",
                "mood": "healthy",
                "category": "all",
            },
        )

        self.assertEqual(response.status_code, 200)
        plan = response.json()

        self.assertEqual(len(plan["days"]), 3)
        self.assertGreater(plan["total_calories"], 0)
        self.assertGreater(len(plan["grocery_list"]), 0)
        recipe_ids = [
            recipe["id"]
            for day in plan["days"]
            for recipe in day["recipes"]
        ]
        self.assertEqual(len(recipe_ids), len(set(recipe_ids)))
        self.assertTrue(all(item["name"] for item in plan["grocery_list"]))


if __name__ == "__main__":
    unittest.main()
