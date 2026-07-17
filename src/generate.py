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
import re
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import challenge as challenge_mod
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


def _dish_hashtags(recipe: dict) -> str:
    """Dish-specific tags on top of the broad set: the broad tags compete
    with millions of posts; #KakarakayaVepudu-style tags own a niche."""
    tags = []
    latin = re.sub(r"[^A-Za-z]", "", recipe["name"])
    if latin:
        tags.append(f"#{latin}")
    te_name = telugu_dish_name(recipe["name"])
    if te_name:
        tags.append("#" + te_name.replace(" ", ""))
    return " ".join(tags)


def build_caption(
    recipe: dict,
    music: Path | None = None,
    challenge: tuple[dict, dict] | None = None,
) -> str:
    # Line 1 is the only line visible before "...more" — it carries the
    # hook + the searchable dish name, never metadata. The old caption
    # spent it on "(Telugu • Curry)" and a date line nobody needs.
    hook = (recipe.get("hook") or "").strip()
    line1 = f"🍽️ {recipe['name']}"
    if hook:
        line1 += f" — {hook}"
    lines = [line1]
    # Telugu-script name doubles the searchable surface (verified map only)
    te_name = telugu_dish_name(recipe["name"])
    if te_name:
        lines.append(f"{te_name} recipe")
    hashtags = HASHTAGS
    if challenge:
        config, state = challenge
        lines.append(f"🏆 {config['name']} — Day {state['day']}/{config['days']}")
        if config.get("hashtags"):
            hashtags = f"{HASHTAGS} {config['hashtags']}"
    # ONE primary CTA, and for reference content it's Save — stacked asks
    # (comment + send + follow all at once) kill each other.
    lines += ["", "🔖 Save cheyandi — recipe mottham caption lo!"]
    lines += ["", "🛒 Ingredients:"]
    lines += [
        f"• {item['measure']} {item['name']}".rstrip() for item in recipe["ingredients"]
    ]
    lines += ["", "👨‍🍳 Method:"]
    lines += [f"{i}. {step}" for i, step in enumerate(recipe["steps"], start=1)]
    if recipe.get("youtube"):
        lines += ["", f"🎥 Video: {recipe['youtube']}"]
    # Secondary ask rotates per post instead of stacking: a comment bait or
    # a share nudge, never both.
    secondary = QUESTIONS + ["📩 Mee intlo cook ki send cheyandi — try chestaru! 👇"]
    lines += ["", secondary[abs(hash(recipe["id"])) % len(secondary)]]
    lines += [f"Follow @{HANDLE} for a new recipe every day! 🔔"]
    # Source credit only where it's true (bank/custom recipes are our own),
    # and no music credit when there is no music — "Recipe data: TheMealDB |
    # Music: ..." read as a bot signature on every post.
    credits = "Recipe data: TheMealDB" if recipe["id"].isdigit() else ""
    if music is not None:
        credits = f"{credits} | Music: {music.stem}".strip(" |")
    dish_tags = _dish_hashtags(recipe)
    hashtags = f"{hashtags} {dish_tags}".strip()
    lines += ["", credits, "", hashtags] if credits else ["", hashtags]

    caption = "\n".join(lines)
    # Instagram's limit is 2200; leave margin since it counts emoji
    # differently than Python, and reserve room for the hashtags we
    # re-append after truncating.
    max_len = 2000
    if len(caption) > max_len:
        keep = max_len - len(hashtags) - 5
        caption = caption[:keep].rsplit("\n", 1)[0] + "\n…\n" + hashtags
    return caption


def main() -> None:
    now_ist = datetime.now(ZoneInfo("Asia/Kolkata"))
    date_str = now_ist.strftime("%Y-%m-%d")

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
    challenge = challenge_mod.active_challenge(root)
    # The dedicated challenge workflow opts in via CHALLENGE. If it opted in
    # but nothing is active (series finished, or config missing), don't post
    # a random daily recipe from the challenge workflow — just stop.
    if challenge_mod.opted_in() and challenge is None:
        print("Challenge finished or unavailable; nothing to post.")
        return
    try:
        # Source order: active challenge -> owner queue -> South Indian bank
        # -> TheMealDB fallback
        recipe = None
        if challenge:
            config, ch_state = challenge
            # This branch runs only in the dedicated challenge workflow. If
            # the challenge dish can't be produced, fail the run rather than
            # posting off-theme content — the day is not silently advanced.
            stem = challenge_mod.pick_stem(root, config, ch_state, set(posted))
            recipe = _bank_recipe_from(root / "recipes" / "bank" / f"{stem}.json")
            print(f"Challenge '{config['name']}' day {ch_state['day']}/{config['days']}: {recipe['name']}")
        if recipe is None:
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
    if challenge:
        config, ch_state = challenge
        day, days = ch_state["day"], config["days"]
        recipe["hook"] = (config.get("hook") or "Day {day}/{days} 🏆").format(day=day, days=days)
        # The story planner frames shots for the challenge angle, and the
        # voiceover opens with the day count instead of the ingredient count
        recipe["story_angle"] = config.get("angle")
        recipe["vo_opener"] = (
            f"Day {day} of our {days}-day healthy food challenge! "
            f"Today: {recipe['name']}."
        )
    elif festival:
        recipe["hook"] = f"{festival} special!"
    # Otherwise the storyboard planner writes a dish-specific hook (set in
    # the reel branch below); "Only N ingredients!" survives only as the
    # last-resort fallback inside assemble_reel.

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
        # Challenge days are always reels (with the usual carousel fallback
        # on generation failure) — a carousel mid-series breaks the format
        fmt = "reel" if challenge else ("reel" if random.random() < REEL_PROBABILITY else "carousel")

    music = None
    vo_lang = None
    reel_kind = None
    if fmt == "reel":
        # Music is opt-in (REEL_MUSIC=1): a generic library track gives
        # neither trending-audio discovery nor brand identity, and its
        # caption credit reads as templated content. The Telangana VO plus
        # the clips' own sizzle IS the reel's original audio.
        music = pick_music(root) if os.environ.get("REEL_MUSIC") == "1" else None
        video_path = posts_dir / f"{date_str}.mp4"

        with tempfile.TemporaryDirectory() as work:
            from ai_reel import BEAT_SECONDS, BEATS_PER_GEN, GEN_SECONDS, TARGET_SECONDS, style_for
            from storyboard import plan_reel

            n_gens = max(1, round(TARGET_SECONDS / GEN_SECONDS))
            # Plan the story ONCE: the same shot list drives both the video
            # beats and the per-shot Telangana narration, so the voice tracks
            # what is on screen. None => template beats + legacy English script.
            plan = plan_reel(recipe, n_gens * BEATS_PER_GEN, style_for(recipe))
            narration = plan["narration"] if plan else None
            story = plan["beats"] if plan else None
            # Dish-specific on-screen hook from the planner; challenge and
            # festival hooks (set above) keep priority.
            if plan and plan.get("hook") and not recipe.get("hook"):
                recipe["hook"] = plan["hook"]

            # VO must fit inside the video with room for the delay + fade
            vo_budget = n_gens * GEN_SECONDS - 2.0
            vo = make_voiceover(
                recipe, HANDLE, Path(work), target_seconds=vo_budget,
                narration=narration, shot_seconds=BEAT_SECONDS,
            )
            vo_lang = vo["lang"] if vo else None
            if vo:
                print(f"  voiceover: {vo['engine']} ({vo['lang']}), {len(vo['segments'])} segment(s)", flush=True)

            try:
                from ai_reel import BACKEND

                key_var = "GEMINI_API_KEY" if BACKEND == "veo" else "KIE_API_KEY"
                if not os.environ.get(key_var):
                    raise RuntimeError(f"{key_var} not set")
                label = "Veo 3.1 (Gemini)" if BACKEND == "veo" else "Kie.ai (Seedance)"
                print(f"Generating AI shot reel via {label}...", flush=True)
                make_ai_reel(recipe, HANDLE, video_path, vo, music, story=story)
                reel_kind = "ai"
            except Exception as exc:
                # Test mode: fail the run rather than publish a fallback
                # carousel (repeated backend tests were spamming the feed)
                if os.environ.get("REQUIRE_REEL"):
                    raise
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
        build_caption(recipe, music, challenge), encoding="utf-8"
    )

    posted.append(recipe["id"])
    posted_path.write_text(json.dumps(posted, indent=0) + "\n")
    if challenge:
        challenge_mod.advance(root, *challenge)

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
