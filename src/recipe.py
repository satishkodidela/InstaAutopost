"""Fetch a random recipe (with dish photo) from TheMealDB's free API."""

import re

import requests

RANDOM_URL = "https://www.themealdb.com/api/json/v1/1/random.php"

# Categories to skip, e.g. ["Beef", "Pork"] for a veg-friendly account.
EXCLUDED_CATEGORIES: list[str] = []

MAX_STEP_CHARS = 260


def _split_steps(instructions: str) -> list[str]:
    """Turn the free-form instructions blob into a list of steps."""
    lines = [ln.strip() for ln in re.split(r"[\r\n]+", instructions) if ln.strip()]
    steps = []
    for line in lines:
        # Drop bare "STEP 1" style markers and leading numbering
        if re.fullmatch(r"(step\s*)?\d+[.):]?", line, re.IGNORECASE):
            continue
        line = re.sub(r"^(step\s*\d+[.):-]?\s*|\d+[.)]\s*)", "", line, flags=re.IGNORECASE)
        # Break up very long paragraphs at sentence boundaries
        while len(line) > MAX_STEP_CHARS:
            cut = line.rfind(". ", 0, MAX_STEP_CHARS)
            if cut == -1:
                break
            steps.append(line[: cut + 1].strip())
            line = line[cut + 1 :].strip()
        if line:
            steps.append(line)
    return steps


def _parse(meal: dict) -> dict:
    ingredients = []
    for i in range(1, 21):
        name = (meal.get(f"strIngredient{i}") or "").strip()
        measure = (meal.get(f"strMeasure{i}") or "").strip()
        if name:
            ingredients.append({"name": name, "measure": measure})
    return {
        "id": meal["idMeal"],
        "name": meal["strMeal"].strip(),
        "category": (meal.get("strCategory") or "").strip(),
        "area": (meal.get("strArea") or "").strip(),
        "thumb": meal.get("strMealThumb") or "",
        "ingredients": ingredients,
        "steps": _split_steps(meal.get("strInstructions") or ""),
        "youtube": meal.get("strYoutube") or "",
        "tags": (meal.get("strTags") or "").strip(),
    }


def fetch_recipe(seen_ids: set[str], attempts: int = 15) -> dict:
    """Fetch a random recipe, skipping already-posted and excluded ones.

    Falls back to whatever it last fetched if every attempt was a repeat
    (better to repeat a dish than to skip a day).
    """
    fallback = None
    for _ in range(attempts):
        resp = requests.get(RANDOM_URL, timeout=20)
        resp.raise_for_status()
        meal = _parse(resp.json()["meals"][0])
        if not meal["thumb"] or not meal["ingredients"] or not meal["steps"]:
            continue
        if meal["category"] in EXCLUDED_CATEGORIES:
            continue
        fallback = meal
        if meal["id"] not in seen_ids:
            return meal
    if fallback is None:
        raise RuntimeError("Could not fetch a usable recipe from TheMealDB.")
    return fallback


def download_photo(url: str) -> bytes:
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    return resp.content
