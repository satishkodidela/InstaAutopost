"""Vision QC gate for generated reel clips.

AI food video fails in recognizable ways — vessels that change identity
between shots, a flame floating directly on the table, ingredients that
morph mid-recipe, foam where oil should be. One detected tell reframes the
whole account as slop for a Telugu audience, so every generated clip is
checked by a vision model against the shot plan before assembly; failing
clips get one bounded regeneration (ai_reel handles the respend cap).

The gate NEVER blocks the day's post: any error — no key, quota, malformed
response — returns "all clips pass" and the pipeline continues.
"""

import json
import os
import re
import subprocess
from pathlib import Path

# Deliberately NOT the STORY_MODEL tunable: QC forces thinking_budget=0,
# which pro-tier Gemini models reject — pinning STORY_MODEL to a pro model
# for better storyboards must not silently disable the vision gate.
QC_MODEL = os.environ.get("QC_MODEL") or "gemini-flash-latest"


def _shot_plan(prompt: str) -> str:
    """The shot-specific part of a generation prompt. Every prompt opens
    with ~870 chars of shared header + style block + prop bible; the QC
    model needs the timed beats ("[0s] ..." / "[00:00-00:04] ..."), not
    identical boilerplate for every clip."""
    m = re.search(r"\[0+s?\]|\[00:", prompt)
    return prompt[m.start():][:600] if m else prompt[-600:]


def _frames(ff: str, clip: Path, fracs: tuple[float, ...] = (0.25, 0.75)) -> list[bytes]:
    """Small JPEG frames sampled inside the clip (as bytes)."""
    from ai_reel import _media_duration  # lazy: ai_reel imports qc lazily too

    dur = _media_duration(ff, clip) or 8.0
    out = []
    for f in fracs:
        r = subprocess.run(
            [ff, "-ss", f"{dur * f:.2f}", "-i", str(clip), "-frames:v", "1",
             "-vf", "scale=512:-2", "-f", "image2pipe", "-c:v", "mjpeg", "-"],
            capture_output=True,
        )
        if r.stdout:
            out.append(r.stdout)
    return out


def qc_clips(ff: str, clips: list[Path], prompts: list[str], recipe: dict, vessel: str) -> list[int]:
    """Indices of clips a viewer would clock as broken/AI; [] on any error."""
    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        parts: list = []
        labels = []
        for i, clip in enumerate(clips):
            frames = _frames(ff, clip)
            if not frames:
                continue
            labels.append(f"Clip {i}: {len(frames)} frames. Planned shots: {_shot_plan(prompts[i])}")
            for frame in frames:
                parts.append(types.Part.from_bytes(data=frame, mime_type="image/jpeg"))
        ing = ", ".join(x["name"] for x in recipe["ingredients"])
        parts.append(
            f"""These frames come from consecutive AI-generated clips of ONE cooking reel
for {recipe['name']} (ingredients: {ing}). Frames are in clip order:
{chr(10).join(labels)}

Judge each clip like a skeptical Telugu home cook scrolling past. Mark
ok=false ONLY for clear violations a casual viewer would notice:
1. Cooking vessel changes identity between clips, or doesn't resemble {vessel}.
2. An open flame burning directly on the table/counter with no stove under the vessel.
3. The main ingredient is visibly the wrong food, or changes cut/form between clips.
4. Grossly wrong hands (extra hands, melted fingers) or physically impossible food
   (falling powder forming connected webs, a full pan of foam instead of oil).
Minor styling issues are NOT failures.

Return ONLY a JSON array, one item per clip:
[{{"clip": <0-based index>, "ok": true/false, "problems": ["<short reason>"]}}]"""
        )
        resp = client.models.generate_content(
            model=QC_MODEL,
            contents=parts,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                max_output_tokens=2048,
                thinking_config=types.ThinkingConfig(thinking_budget=0),
            ),
        )
        verdicts = json.loads(resp.text)
        bad = []
        for v in verdicts:
            if not isinstance(v, dict):
                continue
            i = v.get("clip")
            if not v.get("ok", True) and isinstance(i, int) and 0 <= i < len(clips):
                print(f"  QC: clip {i + 1} flagged — {'; '.join(v.get('problems') or [])[:200]}", flush=True)
                bad.append(i)
        return sorted(set(bad))
    except Exception as exc:
        print(f"  QC skipped ({exc})", flush=True)
        return []
