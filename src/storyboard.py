"""Per-recipe story planning: the shot list comes from how the dish is
actually prepared, not a fixed template.

One Gemini flash call reads the real recipe steps and directs the reel:
a dish-specific money-shot hook, the defining preparation moments in
authentic cooking order, and a loop-closing final shot. Any failure
(no key, quota, malformed JSON) returns None and the caller falls back
to the template beats in ai_reel.build_beats.
"""

import json
import os

# The -latest alias tracks the current flash model; pinned versions get
# retired for new billing accounts (gemini-2.5-flash 404s as of 2026-07)
STORY_MODEL = os.environ.get("STORY_MODEL") or "gemini-flash-latest"


def _prompt(recipe: dict, n_beats: int, style_block: str) -> str:
    name = recipe["name"]
    area = recipe.get("area") or "South Indian"
    ings = ", ".join(i["name"] for i in recipe["ingredients"])
    steps = "\n".join(f"{i + 1}. {s}" for i, s in enumerate(recipe["steps"]))
    angle = ""
    if recipe.get("story_angle"):
        angle = (
            f"\n- Editorial angle for this reel (choose and frame shots to "
            f"serve it while staying true to the recipe): {recipe['story_angle']}"
        )
    return f"""You are directing a short vertical Instagram food reel of {name}, a {area} dish.

The real recipe:
Ingredients: {ings}
Steps:
{steps}

Write exactly {n_beats} shots of 4 seconds each, as a JSON array. Each item:
{{"shot": "<one vivid sentence describing what the camera sees>", "camera": "fixed" or "slow push-in"}}

Rules — realism above all:
- Shots must follow the genuine cooking order of THIS recipe. Show how it is
  actually made: the real technique, textures, and physical actions a home
  cook performs (how batter is spread, how a tadka crackles, how dough is
  rolled). Never invent steps that are not in the recipe.
- Shot 1 is the hook: the single most scroll-stopping, appetizing moment
  unique to this dish (a process moment or the finished dish — whichever is
  more striking for this recipe).
- Shot 2 shows the key ingredients laid out in small brass bowls on the
  counter (a text overlay lists them during this shot).
- Middle shots: the defining preparation moments. One precise action per
  shot, hands entering from the frame edge, food providing the motion.
- The final shot recreates shot 1's framing with the finished {name},
  garnished and steaming, for a seamless loop.
- Fixed setting, identical in every shot: {style_block}
- No people's faces, no fast motion, no artificial speed changes.{angle}

Return ONLY the JSON array, no markdown."""


def plan_story(recipe: dict, n_beats: int, style_block: str) -> list[str] | None:
    """n_beats formatted beat strings from the LLM, or None to use the template."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key or (os.environ.get("REEL_STORY") or "1") == "0":
        return None
    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)
        shots = None
        for attempt in range(2):
            resp = client.models.generate_content(
                model=STORY_MODEL,
                contents=_prompt(recipe, n_beats, style_block),
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    # Without an explicit budget the response can truncate
                    # mid-array; thinking off — shot lists don't need it
                    max_output_tokens=4096,
                    thinking_config=types.ThinkingConfig(thinking_budget=0),
                ),
            )
            try:
                shots = json.loads(resp.text)
                break
            except (json.JSONDecodeError, TypeError) as exc:
                if attempt:
                    raise
                print(f"  story JSON malformed ({exc}); retrying once", flush=True)
        beats = [
            f"{s['shot'].strip().rstrip('.')}. Camera: {s.get('camera', 'fixed')}."
            for s in shots
            if isinstance(s, dict) and s.get("shot", "").strip()
        ]
        if len(beats) < max(2, n_beats - 2):
            raise ValueError(f"story returned {len(beats)}/{n_beats} usable shots")
        # Trim/pad to the exact beat grid, preserving hook and loop close
        while len(beats) > n_beats:
            beats.pop(2)
        while len(beats) < n_beats:
            beats.insert(2, f"macro texture close-up of {recipe['name']}, steam curling. Camera: fixed.")
        return beats
    except Exception as exc:
        print(f"  story planning failed ({exc}); using template beats", flush=True)
        return None
