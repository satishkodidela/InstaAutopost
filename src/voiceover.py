"""Voiceover for the daily reel.

Preferred: Telugu — the English script is translated and voiced via
Sarvam AI (Bulbul v3) when SARVAM_API_KEY is set.
Fallback: free edge-tts (English Indian voice) when Sarvam is missing
or fails, so the pipeline never blocks on the paid service.
"""

import asyncio
import base64
import os
import re
import sys
from pathlib import Path

import requests

SARVAM_BASE = "https://api.sarvam.ai"
SARVAM_SPEAKER = os.environ.get("SARVAM_SPEAKER") or "shreya"
EDGE_VOICE_EN = "en-IN-NeerjaNeural"

def telugu_dish_name(name: str) -> str | None:
    """Telugu-script dish name for bilingual SEO captions; None if unavailable."""
    key = os.environ.get("SARVAM_API_KEY")
    if not key:
        return None
    try:
        return translate_to_telugu(name, key).strip()
    except Exception:
        return None


def _flame_word(celsius: int) -> str:
    if celsius < 150:
        return "low heat"
    if celsius <= 190:
        return "medium heat"
    return "high heat"


def _humanize(text: str) -> str:
    """Make step text speakable: no raw temperatures, units, or fractions.

    TTS reads '180C/160C fan/gas 4' as digits — turn numbers into everyday
    words (high flame, a few minutes, some, half) instead.
    """
    t = text
    # Oven/hob temperature clusters -> low/medium/high heat
    t = re.sub(
        r"\d{2,3}\s*°?\s*C(?:\s*/\s*\d{2,3}\s*°?\s*C\s*fan)?(?:\s*/?\s*gas(?:\s*mark)?\s*\d+)?",
        lambda m: _flame_word(int(re.match(r"\d+", m.group(0)).group(0))),
        t,
        flags=re.IGNORECASE,
    )
    t = re.sub(
        r"\d{3}\s*°?\s*F\b",
        lambda m: _flame_word(round((int(re.match(r"\d+", m.group(0)).group(0)) - 32) / 1.8)),
        t,
    )
    t = re.sub(r"\bgas(?:\s*mark)?\s*\d+\b", "medium heat", t, flags=re.IGNORECASE)
    # Times -> casual
    t = re.sub(r"\d+\s*(?:[-–]|to)\s*\d+\s*(?:mins?|minutes)\b", "a few minutes", t, flags=re.IGNORECASE)
    t = re.sub(r"\d+\s*(?:mins?|minutes)\b", "a few minutes", t, flags=re.IGNORECASE)
    t = re.sub(r"\d+\s*(?:hrs?|hours?)\b", "about an hour", t, flags=re.IGNORECASE)
    # Fractions and measurements -> words
    t = t.replace("1/2", "half").replace("1/4", "a quarter").replace("3/4", "three quarters")
    t = re.sub(r"\d+(?:\.\d+)?\s*(?:kg|g|ml|l|litres?|liters?)\b", "some", t, flags=re.IGNORECASE)
    t = re.sub(r"\d+\s*(?:tbsps?|tsps?|tablespoons?|teaspoons?|cups?)\b", "some", t, flags=re.IGNORECASE)
    return re.sub(r"\s{2,}", " ", t)


DANGLING = {"for", "with", "the", "a", "an", "and", "to", "of", "in", "on", "at", "or", "until", "till"}


def _step_fragment(step: str, max_words: int = 10) -> str:
    words = _humanize(step).split()[:max_words]
    while words and words[-1].lower().rstrip(".,;:") in DANGLING:
        words.pop()
    frag = " ".join(words).rstrip(".,;: ")
    return frag[0].lower() + frag[1:] if frag else ""


def build_script(recipe: dict, handle: str, target_seconds: float = 22.0) -> str:
    """Payoff-first spoken script scaled to the reel length (~2.8 words/sec).

    Written in simple conversational English; Sarvam's code-mixed mode
    turns it into natural everyday Telugu with English words kept in.
    Sentence order mirrors the video beats: hook -> ingredients -> steps
    in order -> serve line over the final reveal -> follow CTA.
    """
    name = recipe["name"]
    n_ing = len(recipe["ingredients"])
    steps = recipe["steps"]

    # Longer reels narrate more steps (24s reel -> 3, 36s -> 4, 48s+ -> 5).
    # Telugu runs ~1.5x longer than the English source, so stay lean.
    n_frags = 3 if target_seconds < 28 else (4 if target_seconds < 40 else 5)
    n_frags = min(n_frags, len(steps))
    stride = (len(steps) - 1) / max(1, n_frags - 1)
    picks = [steps[round(i * stride)] for i in range(n_frags)]
    max_words = 8 if target_seconds < 28 else 10
    frags = [_step_fragment(s, max_words=max_words) for s in picks]

    connectors = ["First,", "Then,", "Next,", "After that,"]
    lines = [
        f"This {name} needs just {n_ing} ingredients!",
        "What you need is on the screen.",
    ]
    for i, frag in enumerate(frags[:-1]):
        lines.append(f"{connectors[min(i, len(connectors) - 1)]} {frag}.")
    lines.append(f"And finally, {frags[-1]}.")
    lines.append("Full recipe in the caption. Follow for a new recipe every day!")
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


def tts_sarvam_telugu(text: str, key: str, out_path: Path, pace: float = 1.0) -> None:
    resp = requests.post(
        f"{SARVAM_BASE}/text-to-speech",
        headers=_sarvam_headers(key),
        json={
            "text": text,
            "target_language_code": "te-IN",
            "model": "bulbul:v3",
            "speaker": SARVAM_SPEAKER,
            "speech_sample_rate": 44100,
            "pace": pace,
        },
        timeout=120,
    )
    if not resp.ok:
        raise RuntimeError(f"Sarvam TTS failed: {resp.text}")
    audio_b64 = resp.json()["audios"][0]
    out_path.write_bytes(base64.b64decode(audio_b64))


def audio_duration(path: Path) -> float:
    import shutil
    import subprocess

    ff = shutil.which("ffmpeg")
    if not ff:
        import imageio_ffmpeg

        ff = imageio_ffmpeg.get_ffmpeg_exe()
    probe = subprocess.run([ff, "-i", str(path)], capture_output=True, text=True)
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", probe.stderr)
    if not m:
        return 0.0
    return float(m.group(1)) * 3600 + float(m.group(2)) * 60 + float(m.group(3))


def tts_edge(text: str, voice: str, out_path: Path) -> None:
    import edge_tts

    async def _run() -> None:
        await edge_tts.Communicate(text, voice).save(str(out_path))

    asyncio.run(_run())


def make_voiceover(
    recipe: dict, handle: str, out_dir: Path, target_seconds: float | None = None
) -> tuple[Path, str] | None:
    """Create the voiceover audio. Returns (path, language) or None.

    Telugu via Sarvam when SARVAM_API_KEY is set; otherwise (or on
    failure) English via free edge-tts; None if everything fails.
    If target_seconds is given and the audio runs longer, it is
    regenerated at a faster pace so it never outlives the video.
    """
    script = build_script(recipe, handle, target_seconds=target_seconds or 22.0)
    sarvam_key = os.environ.get("SARVAM_API_KEY")

    if sarvam_key:
        try:
            telugu = translate_to_telugu(script, sarvam_key)
            path = out_dir / "voiceover.wav"
            tts_sarvam_telugu(telugu, sarvam_key, path)
            if target_seconds:
                dur = audio_duration(path)
                if dur > target_seconds:
                    pace = round(min(1.5, dur / target_seconds + 0.05), 2)
                    print(f"  Voiceover {dur:.1f}s > {target_seconds:.0f}s target; retrying at pace {pace}")
                    tts_sarvam_telugu(telugu, sarvam_key, path, pace=pace)
            return path, "te"
        except Exception as exc:
            print(f"Sarvam voiceover failed, falling back to edge-tts: {exc}", file=sys.stderr)

    try:
        path = out_dir / "voiceover.mp3"
        tts_edge(script, EDGE_VOICE_EN, path)
        if target_seconds:
            dur = audio_duration(path)
            if dur > target_seconds:
                import edge_tts  # rate bump re-render

                rate = f"+{min(50, int((dur / target_seconds - 1) * 100) + 5)}%"

                async def _run() -> None:
                    await edge_tts.Communicate(script, EDGE_VOICE_EN, rate=rate).save(str(path))

                asyncio.run(_run())
        return path, "en"
    except Exception as exc:
        print(f"edge-tts voiceover failed, reel will use music only: {exc}", file=sys.stderr)
        return None
