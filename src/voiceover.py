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
    "Craving something new today?",
    "Here is a dish you have to try!",
    "Tonight's dinner idea, sorted.",
    "One recipe, endless compliments!",
    "This dish takes just a few steps!",
]


def build_script(recipe: dict, handle: str) -> str:
    """A short spoken script (~60-80 words, roughly 25 seconds)."""
    hook = HOOKS[int(recipe["id"]) % len(HOOKS)]
    name = recipe["name"]
    n_ing = len(recipe["ingredients"])
    key_ing = ", ".join(i["name"] for i in recipe["ingredients"][:3])
    n_steps = len(recipe["steps"])
    area = recipe["area"] or "world"
    return (
        f"{hook} Today's recipe of the day is {name}, "
        f"a delicious {area} dish. "
        f"You need just {n_ing} ingredients, including {key_ing}. "
        f"It comes together in {n_steps} simple steps. "
        f"The full ingredients and method are in the caption below. "
        f"Follow us for a new recipe every day!"
    )


def _sarvam_headers(key: str) -> dict:
    return {"api-subscription-key": key, "Content-Type": "application/json"}


def translate_to_telugu(text: str, key: str) -> str:
    last_err = None
    for model in ("sarvam-translate:v1", "mayura:v1"):
        resp = requests.post(
            f"{SARVAM_BASE}/translate",
            headers=_sarvam_headers(key),
            json={
                "input": text,
                "source_language_code": "en-IN",
                "target_language_code": "te-IN",
                "model": model,
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
