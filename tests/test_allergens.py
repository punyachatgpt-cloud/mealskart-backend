"""
Allergen-filter safety tests.

Guards the word-boundary matching + synonym lists in fastapi_app so we never
regress into (a) dangerous false negatives (missing a real allergen) or
(b) over-removal of safe lookalike ingredients.
"""
import fastapi_app as app


def _has(ingredients, allergy, name=""):
    recipe = {"ingredients_list": ingredients, "name": name}
    return app._recipe_has_allergen(recipe, allergy)


# ── Must NOT flag (false positives that the old substring match got wrong) ──
def test_eggplant_is_not_eggs():
    assert _has(["eggplant", "onion"], "eggs") is False


def test_buckwheat_is_not_gluten():
    # Buckwheat is naturally gluten-free despite containing "wheat".
    assert _has(["buckwheat"], "gluten") is False
    assert _has(["buckwheat flour"], "gluten") is False


def test_gluten_free_flours_are_safe():
    for flour in ("rice flour", "corn flour", "besan", "gram flour", "almond flour"):
        assert _has([flour], "gluten") is False, flour


def test_coconut_and_lookalikes_are_not_nuts():
    for term in ("coconut milk", "water chestnut", "butternut squash", "nutmeg"):
        assert _has([term], "nuts") is False, term


# ── MUST flag (false negatives the old keyword list missed = unsafe) ──
def test_hidden_gluten_sources_flagged():
    for term in ("couscous", "bulgur", "seitan", "spelt"):
        assert _has([term], "gluten") is True, term


def test_hidden_allergens_flagged():
    assert _has(["macadamia"], "nuts") is True
    assert _has(["marzipan"], "nuts") is True
    assert _has(["casein powder"], "dairy") is True
    assert _has(["calamari rings"], "seafood") is True
    assert _has(["surimi"], "seafood") is True


# ── Obvious positives still work ──
def test_basic_positives():
    assert _has(["egg", "salt"], "eggs") is True
    assert _has(["almonds"], "nuts") is True            # plural
    assert _has(["wheat flour"], "gluten") is True
    assert _has(["paneer"], "dairy") is True
    assert _has(["prawns"], "seafood") is True
    assert _has(["tofu"], "soy") is True


# ── Conservative: a safe flour mixed with a real allergen is still flagged ──
def test_mixed_safe_and_unsafe_flour_is_flagged():
    assert _has(["rice flour", "whole wheat flour"], "gluten") is True


# ── Neutral dishes pass through ──
def test_plain_dishes_pass():
    assert _has(["rice", "dal", "spinach"], "gluten") is False
    assert _has(["chicken", "tomato", "onion"], "dairy") is False


# ── Whole-pool filter keeps safe recipes, drops unsafe ──
def test_apply_allergy_filter_pool():
    recipes = [
        {"id": 1, "name": "Veg Pulao", "ingredients_list": ["rice", "peas", "carrot"]},
        {"id": 2, "name": "Paneer Tikka", "ingredients_list": ["paneer", "yogurt"]},
        {"id": 3, "name": "Almond Barfi", "ingredients_list": ["almonds", "sugar"]},
    ]
    safe = app.apply_allergy_filter(recipes, ["dairy", "nuts"])
    ids = {r["id"] for r in safe}
    assert ids == {1}
