"""Build a recipes/queue/ JSON file from workflow-dispatch inputs.

Used by .github/workflows/custom-recipe-post.yml so the owner can post
their own recipe from a form instead of hand-writing JSON. Ingredients
and steps are one field each, items separated by ";" or "|" or newlines.
"""

import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests


def split_items(raw: str) -> list[str]:
    return [item.strip() for item in re.split(r"[;|\n]+", raw or "") if item.strip()]


def main() -> None:
    name = (os.environ.get("RECIPE_NAME") or "").strip()
    image_url = (os.environ.get("RECIPE_IMAGE_URL") or "").strip()
    ingredients = split_items(os.environ.get("RECIPE_INGREDIENTS", ""))
    steps = split_items(os.environ.get("RECIPE_STEPS", ""))

    problems = []
    if not name:
        problems.append("name is empty")
    if not image_url.startswith("http"):
        problems.append("image_url must be a public http(s) URL")
    if not ingredients:
        problems.append("ingredients is empty (separate items with ';')")
    if len(steps) < 2:
        problems.append("need at least 2 steps (separate with ';')")
    if problems:
        print("Invalid recipe input: " + "; ".join(problems), file=sys.stderr)
        sys.exit(1)

    try:
        resp = requests.head(image_url, timeout=20, allow_redirects=True)
        if resp.status_code != 200:
            print(f"WARNING: image_url returned HTTP {resp.status_code} — "
                  f"Instagram may fail to fetch it", file=sys.stderr)
    except requests.RequestException as exc:
        print(f"WARNING: image_url not reachable ({exc})", file=sys.stderr)

    recipe = {
        "name": name,
        "category": (os.environ.get("RECIPE_CATEGORY") or "").strip(),
        "area": (os.environ.get("RECIPE_AREA") or "").strip(),
        "image_url": image_url,
        # Whole item text goes in "name"; measure stays empty so cards and
        # captions print it verbatim (e.g. "2 cups basmati rice")
        "ingredients": [{"name": item, "measure": ""} for item in ingredients],
        "steps": steps,
    }

    queue_dir = Path(__file__).resolve().parent.parent / "recipes" / "queue"
    queue_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%Y%m%d-%H%M%S")
    path = queue_dir / f"manual-{stamp}.json"
    path.write_text(json.dumps(recipe, indent=2, ensure_ascii=False) + "\n")

    print(f"Queued {path.name}:")
    print(json.dumps(recipe, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
