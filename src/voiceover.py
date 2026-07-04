"""Voiceover for the daily reel.

Preferred: Telugu — the English script is translated and voiced via
Sarvam AI (Bulbul v3) when SARVAM_API_KEY is set.
Fallback: free edge-tts (English Indian voice) when Sarvam is missing
or fails, so the pipeline never blocks on the paid service.
"""

import asyncio
import base64
import os
import sys
from pathlib import Path

import requests

SARVAM_BASE = "https://api.sarvam.ai"
SARVAM_SPEAKER = os.environ.get("SARVAM_SPEAKER", "shreya")
EDGE_VOICE_EN = "en-IN-NeerjaNeural"

HOOKS = [
    "Guys, you have to try this one!",
    "Okay so, dinner problem solved for today!",
    "Wait till you see how easy this is!",
    "This one is a total crowd pleaser!",
    "Trust me, you will make this again and again!",
]


def _step_fragment(step: str, max_words: int = 10) -> str:
    words = step.split()
    frag = " ".join(words[:max_words]).rstrip(".,;: ")
    return frag[0].lower() + frag[1:] if frag else ""


def build_script(recipe: dict, handle: str) -> str:
    """Casual spoken script (~120 words, roughly 40-45 seconds).

    Written in simple conversational English; Sarvam's code-mixed mode
    turns it into natural everyday Telugu with English words kept in.
    """
    hook = HOOKS[int(recipe["id"]) % len(HOOKS)]
    name = recipe["name"]
    n_ing = len(recipe["ingredients"])
    key_ing = ", ".join(i["name"] for i in recipe["ingredients"][:3])
    steps = recipe["steps"]
    picks = [steps[0]]
    if len(steps) > 2:
        picks.append(steps[len(steps) // 2])
    if len(steps) > 1:
        picks.append(steps[-1])
    frags = [_step_fragment(s) for s in picks]

    lines = [
        f"{hook} Today we are making {name}.",
        f"You just need {n_ing} simple ingredients — the main ones are {key_ing}.",
        f"First, {frags[0]}.",
    ]
    if len(frags) == 3:
        lines.append(f"Then, {frags[1]}.")
    lines.append(f"And finally, {frags[-1]}. That's it, done!")
    lines += [
        "It looks so good, right? The full recipe is there in the caption.",
        "Try it today and tell me how it turned out!",
        "And follow for one tasty new recipe every single day!",
    ]
    return " ".join(lines)


def _sarvam_headers(key: str) -> dict:
    return {"api-subscription-key": key, "Content-Type": "application/json"}


def translate_to_telugu(text: str, key: str) -> str:
    """Conversational code-mixed Telugu (everyday speech, not literary)."""
    last_err = None
    attempts = [
        {"model": "mayura:v1", "mode": "code-mixed"},
        {"model": "mayura:v1", "mode": "modern-colloquial"},
        {"model": "sarvam-translate:v1"},
    ]
    for extra in attempts:
        resp = requests.post(
            f"{SARVAM_BASE}/translate",
            headers=_sarvam_headers(key),
            json={
                "input": text,
                "source_language_code": "en-IN",
                "target_language_code": "te-IN",
                **extra,
            },
            timeout=60,
        )
        if resp.ok:
            return resp.json()["translated_text"]
        last_err = resp.text
    raise RuntimeError(f"Sarvam translate failed: {last_err}")


def tts_sarvam_telugu(text: str, key: str, out_path: Path) -> None:
    resp = requests.post(
        f"{SARVAM_BASE}/text-to-speech",
        headers=_sarvam_headers(key),
        json={
            "text": text,
            "target_language_code": "te-IN",
            "model": "bulbul:v3",
            "speaker": SARVAM_SPEAKER,
            "speech_sample_rate": 44100,
        },
        timeout=120,
    )
    if not resp.ok:
        raise RuntimeError(f"Sarvam TTS failed: {resp.text}")
    audio_b64 = resp.json()["audios"][0]
    out_path.write_bytes(base64.b64decode(audio_b64))


def tts_edge(text: str, voice: str, out_path: Path) -> None:
    import edge_tts

    async def _run() -> None:
        await edge_tts.Communicate(text, voice).save(str(out_path))

    asyncio.run(_run())


def make_voiceover(recipe: dict, handle: str, out_dir: Path) -> tuple[Path, str] | None:
    """Create the voiceover audio. Returns (path, language) or None.

    Telugu via Sarvam when SARVAM_API_KEY is set; otherwise (or on
    failure) English via free edge-tts; None if everything fails.
    """
    script = build_script(recipe, handle)
    sarvam_key = os.environ.get("SARVAM_API_KEY")

    if sarvam_key:
        try:
            telugu = translate_to_telugu(script, sarvam_key)
            path = out_dir / "voiceover.wav"
            tts_sarvam_telugu(telugu, sarvam_key, path)
            return path, "te"
        except Exception as exc:
            print(f"Sarvam voiceover failed, falling back to edge-tts: {exc}", file=sys.stderr)

    try:
        path = out_dir / "voiceover.mp3"
        tts_edge(script, EDGE_VOICE_EN, path)
        return path, "en"
    except Exception as exc:
        print(f"edge-tts voiceover failed, reel will use music only: {exc}", file=sys.stderr)
        return None
