"""Reusable posting challenges (e.g. a 7-day healthy-food week).

Config: recipes/challenges/<slug>.json —
{
  "name": "Healthy Telugu Week",
  "days": 7,
  "angle": "editorial angle fed to the story planner and shot choices",
  "hook": "Day {day}/{days} • Healthy Telugu Week 💪",
  "hashtags": "#HealthyTelugu #7DayChallenge ...",
  "prefer": ["dal", ...], "avoid": ["deep fry", ...]   // optional picker hints
}

State: data/challenge.json (committed by the challenge workflow) —
{"slug": ..., "day": N, "plan": [bank stems], "done": bool}

Activation is env-scoped, NOT file-scoped: a challenge runs only when a
workflow sets CHALLENGE=<slug>. The daily Instagram post never sets it, so
it is fully insulated — a committed data/challenge.json can't divert it.
The state file only persists progress (day/plan/done) between runs of the
dedicated challenge workflow.

On the first run the menu is auto-picked and ordered from the recipe bank
(Gemini ranks it for the angle; keyword scoring is the fallback), then each
successful post advances the day. After the last day the state is marked
done. While active, the challenge takes priority over the owner queue and
the post format is forced to reel (POST_FORMAT still wins).
"""

import json
import os
import re
from pathlib import Path

PICK_MODEL = os.environ.get("STORY_MODEL") or "gemini-flash-latest"

# Built-in healthy-leaning defaults; configs may override via prefer/avoid
PREFER = [
    "dal", "pappu", "pesalu", "moong", "ragi", "millet", "jonna", "sajja",
    "korra", "oats", "fish", "chepa", "egg", "palak", "spinach", "gongura",
    "thotakura", "vegetable", "kura", "rasam", "charu", "majjiga", "curd",
    "perugu", "sprout", "idli", "upma", "sangati", "ulava", "horse gram",
]
AVOID = [
    "deep fry", "deep-fried", "jaggery", "bellam", "sugar", "sweet", "halwa",
    "laddu", "payasam", "burfi", "bobbatlu", "ariselu",
]


def _state_path(root: Path) -> Path:
    return root / "data" / "challenge.json"


def opted_in() -> bool:
    """True when the running workflow asked for a challenge (CHALLENGE set)."""
    return bool(os.environ.get("CHALLENGE"))


def active_challenge(root: Path) -> tuple[dict, dict] | None:
    """(config, state) when a challenge workflow opted in and it isn't finished.

    Env-gated so the daily post workflow (which never sets CHALLENGE) is
    never diverted, even with data/challenge.json present in the repo.
    """
    slug = os.environ.get("CHALLENGE")
    if not slug:
        return None
    cfg_path = root / "recipes" / "challenges" / f"{slug}.json"
    if not cfg_path.exists():
        print(f"Challenge config missing: {cfg_path.name}; skipping")
        return None
    config = json.loads(cfg_path.read_text(encoding="utf-8"))
    path = _state_path(root)
    state = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    # Fresh start, or the workflow switched to a different challenge slug
    if not state or state.get("slug") != slug:
        state = {"slug": slug, "day": 1}
    if state.get("done"):
        return None
    state.setdefault("day", 1)
    return config, state


def _candidates(root: Path, posted: set[str]) -> list[dict]:
    """Bank summaries, unposted first so a challenge favours fresh dishes."""
    out = []
    for p in sorted((root / "recipes" / "bank").glob("*.json")):
        data = json.loads(p.read_text(encoding="utf-8"))
        out.append({
            "stem": p.stem,
            "name": data["name"],
            "category": data.get("category", ""),
            "tags": data.get("tags", ""),
            "ingredients": [i["name"] for i in data["ingredients"]],
            "posted": f"bank-{p.stem}" in posted,
        })
    return sorted(out, key=lambda c: c["posted"])


def _llm_pick(config: dict, candidates: list[dict]) -> list[str]:
    from google import genai
    from google.genai import types

    days = config["days"]
    menu = "\n".join(
        f"- {c['stem']}: {c['name']} ({c['category']}) — {', '.join(c['ingredients'][:8])}"
        for c in candidates
    )
    prompt = f"""Plan a {days}-day Instagram posting series: "{config['name']}".
Editorial angle: {config['angle']}

Choose exactly {days} dishes from this recipe bank (use the stem before the
colon as the identifier) and order them as a satisfying week arc — vary the
meal type day to day (breakfast, light lunch, protein main, comfort dinner),
strongest crowd-pullers on day 1 and the final day:
{menu}

Return ONLY a JSON array of {days} stem strings in posting order."""
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    resp = client.models.generate_content(
        model=PICK_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            max_output_tokens=4096,
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        ),
    )
    valid = {c["stem"] for c in candidates}
    # The array can arrive truncated (missing the closing bracket), so don't
    # rely on json.loads — pull the ordered stems out of the raw text and
    # keep the ones that name a real bank recipe
    text = resp.text or ""
    try:
        raw = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        raw = re.findall(r'"([^"]+)"', text)
    picks = [s for s in raw if isinstance(s, str) and s in valid]
    picks = list(dict.fromkeys(picks))  # dedupe, keep order
    if len(picks) < days:
        raise ValueError(f"planner returned {len(picks)}/{days} valid picks")
    return picks[:days]


def _keyword_pick(config: dict, candidates: list[dict]) -> list[str]:
    prefer = [w.lower() for w in (config.get("prefer") or PREFER)]
    avoid = [w.lower() for w in (config.get("avoid") or AVOID)]

    def score(c: dict) -> int:
        text = " ".join([c["name"], c["category"], c["tags"], *c["ingredients"]]).lower()
        return sum(w in text for w in prefer) - 2 * sum(w in text for w in avoid)

    ranked = sorted(candidates, key=lambda c: (c["posted"], -score(c)))
    return [c["stem"] for c in ranked[: config["days"]]]


def plan_menu(root: Path, config: dict, posted: set[str]) -> list[str]:
    """Auto-pick and order the challenge dishes from the bank."""
    candidates = _candidates(root, posted)
    if len(candidates) < config["days"]:
        raise RuntimeError(
            f"bank has {len(candidates)} recipes, challenge needs {config['days']}"
        )
    if os.environ.get("GEMINI_API_KEY"):
        try:
            return _llm_pick(config, candidates)
        except Exception as exc:
            print(f"  challenge menu LLM pick failed ({exc}); keyword fallback", flush=True)
    return _keyword_pick(config, candidates)


def pick_stem(root: Path, config: dict, state: dict, posted: set[str]) -> str:
    """Today's bank stem; plans the whole menu on the first day."""
    if not state.get("plan"):
        state["plan"] = plan_menu(root, config, posted)
        _state_path(root).write_text(json.dumps(state, indent=2) + "\n")
        names = ", ".join(state["plan"])
        print(f"  challenge menu planned: {names}", flush=True)
    return state["plan"][state["day"] - 1]


def advance(root: Path, config: dict, state: dict) -> None:
    """Move to the next day after a successful post; mark done after the last."""
    state["day"] += 1
    if state["day"] > config["days"]:
        state["done"] = True
    _state_path(root).write_text(json.dumps(state, indent=2) + "\n")
