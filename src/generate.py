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
from hero_image import generate_hero
from recipe import download_photo, fetch_recipe
from voiceover import make_voiceover, telugu_dish_name

MAX_STEP_CARDS = 3
# Overridable via env / repo variables (empty values fall through)
HANDLE = os.environ.get("IG_HANDLE") or "roadside_mobile"
REEL_PROBABILITY = float(os.environ.get("REEL_PROBABILITY") or "0.5")

HASHTAGS = (
    "#TeluguRecipes #TeluguVantalu #SouthIndianFood #AndhraRecipes "
    "#TeluguFood #RecipeOfTheDay #HomeCooking #EasyRecipes #DailyRecipe"
)

# Comment-bait questions rotate by recipe id (comment count is a ranking signal)
QUESTIONS = [
    "Mee intlo kuda ila chestara? Comment cheyandi! 👇",
    "Amma style or this style — which one wins? Comment! 👇",
    "Rate this recipe 1-10 in the comments! 👇",
    "Which dish should we make tomorrow? Tell us below! 👇",
    "Tried this before? How did it turn out? 👇",
]


def pick_music(root: Path) -> Path | None:
    tracks = sorted((root / "assets" / "music").glob("*.mp3"))
    return random.choice(tracks) if tracks else None


def pop_queued_recipe(root: Path) -> dict | None:
    """Owner-supplied recipe queue: recipes/queue/*.json, oldest first.

    Takes priority over TheMealDB. The consumed file is deleted (the
    workflow commits the deletion). See recipes/README.md for the schema.
    """
    queue = sorted((root / "recipes" / "queue").glob("*.json"))
    if not queue:
        return None
    path = queue[0]
    data = json.loads(path.read_text(encoding="utf-8"))
    recipe = {
        "id": f"custom-{path.stem}",
        "name": data["name"],
        "category": data.get("category", ""),
        "area": data.get("area", ""),
        "thumb": data["image_url"],
        "ingredients": [
            {"name": i["name"], "measure": i.get("measure", "")}
            for i in data["ingredients"]
        ],
        "steps": data["steps"],
        "youtube": data.get("youtube", ""),
        "tags": data.get("tags", ""),
    }
    path.unlink()
    print(f"Using queued custom recipe: {recipe['name']} ({path.name})")
    return recipe


def load_history(path: Path) -> list[dict]:
    return json.loads(path.read_text()) if path.exists() else []


def _bank_recipe_from(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    return {
        "id": f"bank-{path.stem}",
        "name": data["name"],
        "category": data.get("category", ""),
        "area": data.get("area", "South Indian"),
        "thumb": data.get("image_url", ""),
        "ingredients": [
            {"name": i["name"], "measure": i.get("measure", "")}
            for i in data["ingredients"]
        ],
        "steps": data["steps"],
        "youtube": data.get("youtube", ""),
        "tags": data.get("tags", ""),
    }


def upcoming_festival(root: Path, today, window_days: int = 3) -> dict | None:
    """Festival within the next `window_days` (data/festivals.json, MM-DD dates)."""
    path = root / "data" / "festivals.json"
    if not path.exists():
        return None
    from datetime import date, timedelta

    for fest in json.loads(path.read_text(encoding="utf-8")):
        month, day = (int(x) for x in fest["date"].split("-"))
        for year in (today.year, today.year + 1):
            try:
                fd = date(year, month, day)
            except ValueError:
                continue
            if 0 <= (fd - today).days <= window_days:
                return fest
    return None


def pick_bank_recipe(root: Path, posted: set[str], today) -> tuple[dict | None, str | None]:
    """South Indian bank pick: festival-tagged first, else random unposted.

    Returns (recipe, festival_name_or_None).
    """
    bank = sorted((root / "recipes" / "bank").glob("*.json"))
    unposted = [p for p in bank if f"bank-{p.stem}" not in posted]
    if not unposted:
        return None, None

    fest = upcoming_festival(root, today)
    if fest:
        tags = set(fest.get("tags", []))
        for path in unposted:
            data = json.loads(path.read_text(encoding="utf-8"))
            recipe_tags = set((data.get("tags") or "").split(","))
            if tags & recipe_tags:
                return _bank_recipe_from(path), fest["name"]
    return _bank_recipe_from(random.choice(unposted)), None


def build_caption(recipe: dict, date_label: str, music: Path | None = None) -> str:
    # Bilingual keyword-first title: Instagram/Google index caption keywords,
    # and the Telugu-script name doubles the searchable surface
    title = f"{recipe['name']} recipe"
    te_name = telugu_dish_name(recipe["name"])
    if te_name:
        title = f"{recipe['name']} | {te_name} recipe"
    meta = " • ".join(filter(None, [recipe["area"], recipe["category"]]))
    lines = [f"🍽️ {title}"]
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
    question = QUESTIONS[abs(hash(recipe["id"])) % len(QUESTIONS)]
    lines += ["", question]
    lines += ["📩 Send this to a foodie friend & 🔖 save it for later!"]
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
    history_path = data_dir / "history.json"
    history = load_history(history_path)
    last_post = history[-1] if history else None
    if last_post:
        print(f"Last post: {last_post.get('name')} [{last_post.get('format')}] "
              f"on {last_post.get('date')}")

    festival = None
    try:
        # Source order: owner queue -> South Indian bank -> TheMealDB fallback
        recipe = pop_queued_recipe(root)
        if recipe is None:
            recipe, festival = pick_bank_recipe(root, set(posted), now_ist.date())
            if recipe is not None:
                print(f"Bank recipe: {recipe['name']}"
                      + (f" ({festival} special)" if festival else ""))
        if recipe is None:
            print("Bank exhausted; falling back to TheMealDB")
            recipe = fetch_recipe(
                seen_ids=set(posted),
                avoid_category=(last_post or {}).get("category"),
            )

        # Bank recipes without a photo get an AI hero image (cover + @image1 anchor)
        if not recipe.get("thumb"):
            if not os.environ.get("KIE_API_KEY"):
                raise RuntimeError(f"{recipe['name']} has no image_url and no KIE_API_KEY for hero generation")
            print("Generating hero image...", flush=True)
            recipe["thumb"] = generate_hero(recipe, os.environ["KIE_API_KEY"])

        photo = download_photo(recipe["thumb"])
    except Exception as exc:
        print(f"Failed to prepare recipe: {exc}", file=sys.stderr)
        sys.exit(1)

    # Series hooks for the reel overlay
    if festival:
        recipe["hook"] = f"{festival} special!"
    elif len(recipe["ingredients"]) <= 5:
        recipe["hook"] = f"Only {len(recipe['ingredients'])} ingredients!"

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

    history.append(
        {
            "date": date_str,
            "name": recipe["name"],
            "category": recipe["category"],
            "area": recipe["area"],
            "format": fmt,
            "kind": reel_kind,
            "voiceover": vo_lang,
        }
    )
    history_path.write_text(json.dumps(history, indent=2) + "\n")

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
