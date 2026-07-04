"""Generate today's recipe post: fetch a recipe, render cards, write caption.

Randomly posts as either an image carousel or a Reel (slideshow video of
the same cards with optional background music from assets/music/).

Outputs posts/YYYY-MM-DD-1.jpg (photo cover), -2.jpg (ingredients),
-3.jpg[...] (method), a follow card, posts/YYYY-MM-DD.txt (caption), and —
when the Reel format is drawn — posts/YYYY-MM-DD.mp4 (publish.py posts the
video when it exists, the images otherwise). Dated in IST. Tracks posted
recipe IDs in data/posted.json to avoid repeats.

Set POST_FORMAT=reel or POST_FORMAT=carousel to override the random draw.
"""

import json
import os
import random
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from ai_reel import make_ai_reel
from card import make_cover, make_follow_card, make_ingredients_card, make_steps_cards
from recipe import download_photo, fetch_recipe
from voiceover import make_voiceover

MAX_STEP_CARDS = 3
HANDLE = "roadside_mobile"
REEL_PROBABILITY = 0.5

HASHTAGS = (
    "#RecipeOfTheDay #Foodie #HomeCooking #EasyRecipes #FoodLovers "
    "#Cooking #InstaFood #FoodStagram #DailyRecipe"
)


def pick_music(root: Path) -> Path | None:
    tracks = sorted((root / "assets" / "music").glob("*.mp3"))
    return random.choice(tracks) if tracks else None


def build_caption(recipe: dict, date_label: str, music: Path | None = None) -> str:
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
    lines += ["", f"🔖 Save this recipe for later & share it with a foodie!"]
    lines += [f"Follow @{HANDLE} for a new recipe every day! 🔔"]
    credits = "Recipe data: TheMealDB"
    if music is not None:
        credits += f" | Music: {music.stem}"
    lines += ["", credits, "", HASHTAGS]

    caption = "\n".join(lines)
    # Instagram's limit is 2200; leave margin since it counts emoji
    # differently than Python, and reserve room for the hashtags we
    # re-append after truncating.
    max_len = 2000
    if len(caption) > max_len:
        keep = max_len - len(HASHTAGS) - 5
        caption = caption[:keep].rsplit("\n", 1)[0] + "\n…\n" + HASHTAGS
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
    step_cards = make_steps_cards(recipe, first_page=2, out_paths=step_paths, extra_pages=1)
    total_pages = 2 + step_cards + 1

    make_cover(photo, recipe, total_pages, str(posts_dir / f"{date_str}-1.jpg"))
    make_ingredients_card(recipe, 1, total_pages, str(posts_dir / f"{date_str}-2.jpg"))
    make_follow_card(
        HANDLE,
        total_pages - 1,
        total_pages,
        str(posts_dir / f"{date_str}-{total_pages}.jpg"),
    )

    fmt = os.environ.get("POST_FORMAT")
    if fmt not in ("reel", "carousel"):
        fmt = "reel" if random.random() < REEL_PROBABILITY else "carousel"

    music = None
    vo_lang = None
    reel_kind = None
    if fmt == "reel":
        music = pick_music(root)
        video_path = posts_dir / f"{date_str}.mp4"

        with tempfile.TemporaryDirectory() as work:
            vo = make_voiceover(recipe, HANDLE, Path(work))
            vo_path = None
            if vo is not None:
                vo_path, vo_lang = vo

            try:
                if not os.environ.get("KIE_API_KEY"):
                    raise RuntimeError("KIE_API_KEY not set")
                print("Generating AI shot reel via Kie.ai (Seedance)...", flush=True)
                make_ai_reel(recipe, HANDLE, video_path, vo_path, music)
                reel_kind = "ai"
            except Exception as exc:
                # No card-slideshow fallback (rejected by account owner) —
                # post the carousel instead so the day never goes empty.
                print(f"AI reel unavailable, posting carousel instead: {exc}", file=sys.stderr)
                fmt = "carousel"
                reel_kind = None
                music = None
                vo_lang = None
                video_path.unlink(missing_ok=True)
    else:
        # A leftover video from an earlier run today would make publish.py
        # post a reel instead of the carousel
        (posts_dir / f"{date_str}.mp4").unlink(missing_ok=True)

    (posts_dir / f"{date_str}.txt").write_text(
        build_caption(recipe, date_label, music), encoding="utf-8"
    )

    posted.append(recipe["id"])
    posted_path.write_text(json.dumps(posted, indent=0) + "\n")

    fmt_label = f"{fmt}:{reel_kind}" if reel_kind else fmt
    print(f"Generated {total_pages} cards for: {recipe['name']} [{fmt_label}]")
    print(f"  Cuisine: {recipe['area']} | Category: {recipe['category']}")
    print(f"  {len(recipe['ingredients'])} ingredients, {len(recipe['steps'])} steps")
    if vo_lang is not None:
        print(f"  Voiceover: {vo_lang}")
    if music is not None:
        print(f"  Music: {music.name}")


if __name__ == "__main__":
    main()
