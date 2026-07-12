"""Per-recipe story planning: the shot list — and the narration spoken over
it — come from how the dish is actually prepared, not a fixed template.

One Gemini call reads the real recipe steps and returns, per 4-second shot:
a vivid English visual direction (drives the video prompt/keyframes) and one
natural, conversational Telangana-Telugu narration line (drives the
voiceover). Authoring both together is what makes the voice describe what is
actually on screen. Any failure (no key, quota, malformed JSON) returns None
and callers fall back to the template beats / mechanical English script.
"""

import json
import os

# The -latest alias tracks the current flash model; pinned versions get
# retired for new billing accounts (gemini-2.5-flash 404s as of 2026-07)
STORY_MODEL = os.environ.get("STORY_MODEL") or "gemini-flash-latest"


def _prompt(recipe: dict, n_beats: int, style_block: str, narrate: bool) -> str:
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

    if narrate:
        item = (
            '{"shot": "<one vivid ENGLISH sentence describing what the camera sees>", '
            '"camera": "fixed" or "slow push-in", '
            '"vo": "<one natural spoken line in TELANGANA TELUGU (Telugu script) for THIS shot>"}'
        )
    else:
        item = (
            '{"shot": "<one vivid sentence describing what the camera sees>", '
            '"camera": "fixed" or "slow push-in"}'
        )

    vo_rules = ""
    if narrate:
        opener = ""
        if recipe.get("vo_opener"):
            opener = (
                f'\n- The FIRST shot\'s "vo" must open by conveying this, naturally in '
                f'Telangana Telugu: "{recipe["vo_opener"]}"'
            )
        vo_rules = f"""

Narration ("vo") rules — a real person talking to a friend, NOT reading steps:
- Write CONVERSATIONAL TELANGANA TELUGU in Telugu script — the everyday
  Hyderabad/Telangana dialect. Use its words and verb endings: మస్తు, గిట్ల,
  ఇగ, పోదాం, చేద్దాం, ఏందీ, ఉంటది, తీస్కో, కలిపేయ్, సుడు, భలే. NEVER formal or
  literary Telugu, and NEVER English sentences.
- ONE short line per shot, about 6-7 words — it must be speakable inside a
  4-second shot.
- Each line talks about what THAT shot shows, in real cooking order — like
  you're narrating your own cooking to a friend, warm and a little playful.
- Spell any quantity as an everyday word (కొంచెం, కాస్త, గుప్పెడు), never
  digits or units.{opener}
- The LAST shot's "vo" is a warm follow call-to-action in Telangana Telugu
  (e.g. "ఇలాంటి రుచులకి మమ్మల్ని ఫాలో అవ్వుండ్రి")."""

    return f"""You are directing a short vertical Instagram food reel of {name}, a {area} dish.

The real recipe:
Ingredients: {ings}
Steps:
{steps}

Write exactly {n_beats} shots of 4 seconds each, as a JSON array. Each item:
{item}

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
- No people's faces, no fast motion, no artificial speed changes.{angle}{vo_rules}

Return ONLY the JSON array, no markdown."""


def _generate_shots(recipe: dict, n_beats: int, style_block: str, narrate: bool):
    """Raw shot dicts from the LLM, trimmed/padded to exactly n_beats; None if disabled."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key or (os.environ.get("REEL_STORY") or "1") == "0":
        return None
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)
    shots = None
    for attempt in range(2):
        resp = client.models.generate_content(
            model=STORY_MODEL,
            contents=_prompt(recipe, n_beats, style_block, narrate),
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                # Narration roughly doubles the payload; give headroom so the
                # JSON array never truncates mid-shot
                max_output_tokens=8192,
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

    valid = [s for s in shots if isinstance(s, dict) and s.get("shot", "").strip()]
    if len(valid) < max(2, n_beats - 2):
        raise ValueError(f"story returned {len(valid)}/{n_beats} usable shots")
    # Trim/pad the SHOT list to exactly n_beats, preserving the hook (0-1) and
    # loop close (last), so beats and narration stay in lockstep
    filler = {
        "shot": f"macro texture close-up of {recipe['name']}, steam curling",
        "camera": "fixed",
        "vo": "",
    }
    while len(valid) > n_beats:
        valid.pop(2)
    while len(valid) < n_beats:
        valid.insert(2, dict(filler))
    return valid


def _beat(shot: dict) -> str:
    return f"{shot['shot'].strip().rstrip('.')}. Camera: {shot.get('camera', 'fixed')}."


def plan_reel(recipe: dict, n_beats: int, style_block: str) -> dict | None:
    """{'beats': [...], 'narration': [...]}, both length n_beats, or None.

    beats drive the video prompts/keyframes; narration is the per-shot
    Telangana-Telugu voiceover, aligned 1:1 to the beats.
    """
    try:
        shots = _generate_shots(recipe, n_beats, style_block, narrate=True)
        if not shots:
            return None
        return {
            "beats": [_beat(s) for s in shots],
            "narration": [(s.get("vo") or "").strip() for s in shots],
        }
    except Exception as exc:
        print(f"  story planning failed ({exc}); using template beats", flush=True)
        return None


def plan_story(recipe: dict, n_beats: int, style_block: str) -> list[str] | None:
    """n_beats video beat strings, or None to use the template. Thin wrapper
    over plan_reel for callers (keyframes, standalone make_ai_reel) that only
    need the visual beats."""
    plan = plan_reel(recipe, n_beats, style_block)
    return plan["beats"] if plan else None
