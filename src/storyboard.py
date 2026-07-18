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
import re
from datetime import date

# The -latest alias tracks the current flash model; pinned versions get
# retired for new billing accounts (gemini-2.5-flash 404s as of 2026-07)
STORY_MODEL = os.environ.get("STORY_MODEL") or "gemini-flash-latest"

# On-screen hook archetypes, rotated by day so the feed never shows the same
# templated line twice in a row ("Only N ingredients!" ran every single day).
# The LLM writes the actual line from the recipe's own differentiator.
HOOK_ARCHETYPES = [
    "objection-killer: name the doubt everyone has about this dish "
    "(too bitter, too oily, soggy, hard to get right) and promise this "
    "recipe solves it",
    "secret trick: tease the ONE technique in these steps that changes "
    "the result",
    "common mistake: call out the mistake most people make with this dish",
    "craving/nostalgia: the amma's-kitchen or childhood-memory angle that "
    "makes a Telugu viewer stop",
    "bold claim: a confident, specific claim about taste or texture this "
    "recipe earns",
]


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

    cam_keys = (
        '"scale": "extreme close-up" | "close-up" | "medium shot" | '
        '"overhead top-down" | "wide shot", '
        '"angle": "eye level" | "high 45-degree" | "low angle" | "overhead", '
        '"move": "locked off" | "slow push-in" | "slow orbit" | '
        '"slow tilt-up reveal" | "rack focus"'
    )
    if narrate:
        item = (
            '{"shot": "<one vivid ENGLISH sentence describing what the camera sees>", '
            + cam_keys + ', '
            '"vo": "<one natural spoken line in TELANGANA TELUGU (Telugu script) for THIS shot>"}'
        )
    else:
        item = (
            '{"shot": "<one vivid sentence describing what the camera sees>", '
            + cam_keys + '}'
        )

    archetype = HOOK_ARCHETYPES[date.today().timetuple().tm_yday % len(HOOK_ARCHETYPES)]
    hook_rules = f"""
- The FIRST item must ALSO carry a key "hook": the on-screen headline for
  shot 1. Write it as this archetype — {archetype}. Rules: max 7 words,
  conversational code-mixed Telugu written ENTIRELY in Telugu script —
  everyday English words transliterated into Telugu letters (ట్రిక్,
  సీక్రెట్, పర్ఫెక్ట్) are perfect. No Latin letters, no digits, no emoji
  (the overlay font only has Telugu glyphs). Concrete to THIS dish — never
  a generic line like "Only N ingredients!" — and a claim the recipe
  actually delivers."""

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
- ONE short line per shot, about 5-6 words — it must be speakable, unhurried,
  inside a 4-second shot. Keep it breezy, not crammed.
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
- Shot 1 is the hook and MUST show the FINISHED {name} at its most
  appetizing — glossy, textured, steaming, ready to eat. Never a raw,
  mid-boil, or half-cooked state: the first frame decides the scroll, and
  wet mid-cook food loses it.
- Shot 2 shows the key ingredients laid out in small bowls on the counter —
  exactly ONE bowl per ingredient, no duplicates, each clearly the real
  ingredient (a text overlay points to the caption during this shot).
- Middle shots: the defining preparation moments IN ORDER, as one continuous
  process — each shot advancing the cooking from the previous, no jumps. Pick
  the most important transformations and show the dish visibly progressing,
  including the moment the dish reaches its final cooked texture.
- If there are at least 5 shots, the SECOND-TO-LAST shot must be the serving
  payoff: the finished {name} served the way it is actually eaten (over hot
  steaming rice, onto a plate or banana leaf, a spoon lifting a portion) —
  this is the moment a Telugu viewer shares.
- The final shot recreates shot 1's framing with the finished {name},
  garnished and steaming, and must END MID-ACTION (steam still rising, a
  sprinkle mid-fall) so looping back to shot 1 reads as continuous motion.
- Cinematography — direct like a food-film DP, one primary camera idea per
  shot (choose scale/angle/move from the allowed values only):
  * Shot 1: extreme close-up or close-up of the finished dish, slow push-in.
  * The ingredients shot: overhead top-down, locked off.
  * Include at least ONE extreme close-up texture moment mid-process (oil
    shimmering, spice coating clinging, steam curling off the surface).
  * The serving shot: high 45-degree or low angle — the hero angle.
  * The final shot repeats shot 1's scale and angle exactly (the loop).
  * Never give two consecutive shots the same scale AND angle — change at
    least one between neighbours; cutting between identical framings reads
    as a jump cut.
  * Movement is always slow and subtle — the food provides the motion.
- Physical realism in every shot: tempering is clear shimmering oil with
  mustard seeds crackling (never foam or froth), powders are sprinkled from
  a small spoon (never crumbled from fingers), liquids pour in thin streams,
  and the cooking vessel always sits on a stove — a home cook must see
  nothing physically impossible.
- Fixed setting, identical in every shot: {style_block}
- No people's faces, no fast motion, no artificial speed changes.{angle}{hook_rules}{vo_rules}

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


# Cinematic camera vocabulary (Veo interprets professional film terms with
# high fidelity; Google's guide: lead the prompt with cinematography, keep
# ONE primary camera movement per shot, phrased as its own sentence).
SCALES = ("extreme close-up", "close-up", "medium shot", "overhead top-down", "wide shot")
ANGLES = {
    "eye level": "eye level",
    "high 45-degree": "a high 45-degree angle",
    "low angle": "a low angle",
    "overhead": "directly overhead",
}
MOVES = ("locked off", "slow push-in", "slow orbit", "slow tilt-up reveal", "rack focus")


def _camera_spec(shot: dict) -> tuple[str, str, str] | None:
    """Normalized (scale, angle, move), or None when the LLM used the legacy
    single "camera" string (or nothing usable)."""
    scale = (shot.get("scale") or "").strip().lower()
    if scale not in SCALES:
        return None
    angle = (shot.get("angle") or "").strip().lower()
    move = (shot.get("move") or "").strip().lower()
    return (
        scale,
        angle if angle in ANGLES else "eye level",
        move if move in MOVES else "locked off",
    )


def _apply_cinematography(shots: list[dict]) -> None:
    """Normalize per-shot camera specs and enforce the editor rules the LLM
    tends to drift on: the loop close mirrors shot 1's framing, and adjacent
    shots never share the same scale+angle (reads as a jump cut)."""
    specs = [_camera_spec(s) for s in shots]
    if specs[0] is None:
        return  # legacy plan — leave the old "camera" strings alone
    for i, sp in enumerate(specs):
        if sp is None:
            specs[i] = ("close-up", "eye level", "locked off")
    specs[-1] = (specs[0][0], specs[0][1], specs[-1][2])  # loop mirrors the hook
    for i in range(1, len(specs) - 1):
        if (specs[i][0], specs[i][1]) == (specs[i - 1][0], specs[i - 1][1]):
            for alt in ("close-up", "medium shot", "extreme close-up", "wide shot"):
                if alt != specs[i - 1][0]:
                    specs[i] = (alt, specs[i][1], specs[i][2])
                    break
    for shot, (scale, angle, move) in zip(shots, specs):
        shot["scale"], shot["angle"], shot["move"] = scale, angle, move


def _beat(shot: dict) -> str:
    """Compose the video-prompt beat: cinematography FIRST (scale+angle open
    the shot line — keyframes compose from it too), the movement after
    "Camera:" so keyframes.state_text can strip what a still can't show."""
    text = shot["shot"].strip().rstrip(".")
    spec = _camera_spec(shot)
    if spec is None:
        return f"{text}. Camera: {shot.get('camera', 'fixed')}."
    scale, angle, move = spec
    head = (
        "Overhead top-down shot" if scale == "overhead top-down"
        else f"{scale.capitalize()} from {ANGLES[angle]}"
    )
    return f"{head}: {text}. Camera: {move}."


def plan_reel(recipe: dict, n_beats: int, style_block: str) -> dict | None:
    """{'beats': [...], 'narration': [...], 'hook': str|None}, or None.

    beats drive the video prompts/keyframes; narration is the per-shot
    Telangana-Telugu voiceover, aligned 1:1 to the beats; hook is the
    on-screen headline for shot 1 (dish-specific, archetype-rotated).
    """
    try:
        shots = _generate_shots(recipe, n_beats, style_block, narrate=True)
        if not shots:
            return None
        _apply_cinematography(shots)
        hook = (shots[0].get("hook") or "").strip() or None
        # The overlay renders each block with ONE font: Noto Sans Telugu has
        # no Latin letters and no emoji, DejaVu has no Telugu. A Telugu hook
        # must therefore contain ONLY glyphs Noto Telugu covers (whitelist —
        # a blacklist can't anticipate every emoji/foreign script the LLM
        # might sneak in); a pure-Latin hook renders via DejaVu and is fine.
        if hook and re.search(r"[ఀ-౿]", hook):
            if not re.fullmatch(
                r"[ఀ-౿0-9\s‌‍.,:;!?'\"“”‘’\-–—…()]+", hook
            ):
                print(f"  hook has unrenderable characters, dropping: {hook}", flush=True)
                hook = None
        return {
            "beats": [_beat(s) for s in shots],
            "narration": [(s.get("vo") or "").strip() for s in shots],
            "hook": hook,
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
