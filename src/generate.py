"""Generate today's recipe carousel: fetch a recipe, render cards, write caption.

Outputs posts/YYYY-MM-DD-1.jpg (photo cover), -2.jpg (ingredients),
-3.jpg[, -4.jpg] (method), and posts/YYYY-MM-DD.txt (caption), dated in IST.
Tracks posted recipe IDs in data/posted.json to avoid repeats.
"""

import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from card import make_cover, make_ingredients_card, make_steps_cards
from recipe import download_photo, fetch_recipe

MAX_STEP_CARDS = 3

HASHTAGS = (
    "#RecipeOfTheDay #Foodie #HomeCooking #EasyRecipes #FoodLovers "
    "#Cooking #InstaFood #FoodStagram #DailyRecipe"
)


def build_caption(recipe: dict, date_label: str) -> str:
    meta = " • ".join(filter(None, [recipe["area"], recipe["category"]]))
    lines = [f"🍽️ Recipe of the Day — {recipe['name']}"]
    if meta:
        lines.append(f"({meta})")
    lines += ["", f"📅 {date_label}", "", "🛒 Ingredients:"]
    lines += [
        f"• {item['measure']} {item['name']}".rstrip() for item in recipe["ingredients"]
    ]
    lines += ["", "👨‍🍳 Method:"]
    lines += [f"{i}. {step}" for i, step in enumerate(recipe["steps"], start=1)]
    if recipe.get("youtube"):
        lines += ["", f"🎥 Video: {recipe['youtube']}"]
    lines += ["", "Recipe data: TheMealDB", "", HASHTAGS]

    caption = "\n".join(lines)
    if len(caption) > 2150:  # Instagram caption limit is 2200 chars
        caption = caption[:2150].rsplit("\n", 1)[0] + "\n…\n" + HASHTAGS
    return caption


def main() -> None:
    now_ist = datetime.now(ZoneInfo("Asia/Kolkata"))
    date_str = now_ist.strftime("%Y-%m-%d")
    date_label = now_ist.strftime("%A, %d %B %Y")

    root = Path(__file__).resolve().parent.parent
    posts_dir = root / "posts"
    posts_dir.mkdir(exist_ok=True)
    data_dir = root / "data"
    data_dir.mkdir(exist_ok=True)
    posted_path = data_dir / "posted.json"

    posted: list[str] = (
        json.loads(posted_path.read_text()) if posted_path.exists() else []
    )

    try:
        recipe = fetch_recipe(seen_ids=set(posted))
        photo = download_photo(recipe["thumb"])
    except Exception as exc:
        print(f"Failed to fetch recipe: {exc}", file=sys.stderr)
        sys.exit(1)

    # Method cards first — their count determines the page total shown
    # in the cover/ingredients page dots.
    step_paths = [
        str(posts_dir / f"{date_str}-{3 + i}.jpg") for i in range(MAX_STEP_CARDS)
    ]
    step_cards = make_steps_cards(recipe, first_page=2, out_paths=step_paths)
    total_pages = 2 + step_cards

    make_cover(photo, recipe, total_pages, str(posts_dir / f"{date_str}-1.jpg"))
    make_ingredients_card(recipe, 1, total_pages, str(posts_dir / f"{date_str}-2.jpg"))

    (posts_dir / f"{date_str}.txt").write_text(
        build_caption(recipe, date_label), encoding="utf-8"
    )

    posted.append(recipe["id"])
    posted_path.write_text(json.dumps(posted, indent=0) + "\n")

    print(f"Generated {total_pages} cards for: {recipe['name']}")
    print(f"  Cuisine: {recipe['area']} | Category: {recipe['category']}")
    print(f"  {len(recipe['ingredients'])} ingredients, {len(recipe['steps'])} steps")


if __name__ == "__main__":
    main()
