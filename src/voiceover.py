"""Voiceover for the daily reel.

Two shapes of output, both returned as a structured result
(``{"segments": [...], "lang", "engine"}``; see ``make_voiceover``):

- Per-shot narration (preferred): one natural Telangana-Telugu line per
  video shot (from storyboard.plan_reel), each synthesised as its own
  segment and anchored to that shot's start time, so the voice describes
  what is on screen. Primary engine is ElevenLabs ``eleven_v3`` (the only
  model that speaks Telugu) in a stock or cloned voice, with character-level
  timestamps for karaoke captions; Sarvam Bulbul v3 is the Telugu fallback.
- Legacy single blob (last resort): the mechanical English script voiced by
  free edge-tts when no narration and no paid Telugu engine is available, so
  the pipeline never blocks.

Priority: ElevenLabs -> Sarvam -> edge-tts -> music only.
"""

import asyncio
import base64
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import requests

SARVAM_BASE = "https://api.sarvam.ai"
SARVAM_SPEAKER = os.environ.get("SARVAM_SPEAKER") or "shreya"
EDGE_VOICE_EN = "en-IN-NeerjaNeural"

# ElevenLabs (Telugu only renders on eleven_v3). The owner's key is stored as
# ELEVEN_LABS_API_KEY; ELEVENLABS_API_KEY is accepted as the SDK-style alias.
ELEVEN_BASE = "https://api.elevenlabs.io/v1"
ELEVEN_KEY = os.environ.get("ELEVEN_LABS_API_KEY") or os.environ.get("ELEVENLABS_API_KEY")
ELEVEN_VOICE = os.environ.get("ELEVEN_LABS_VOICE_ID") or os.environ.get("ELEVENLABS_VOICE_ID")
ELEVEN_MODEL = os.environ.get("ELEVEN_LABS_MODEL") or "eleven_v3"
ELEVEN_FORMAT = os.environ.get("ELEVEN_LABS_FORMAT") or "mp3_44100_128"
# Lower stability = more expressive/conversational (less flat/robotic).
ELEVEN_STABILITY = float(os.environ.get("ELEVEN_LABS_STABILITY") or "0.35")


def _ff() -> str:
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()

# Verified Telugu-script names for the dish bank. These are romanized Telugu
# proper nouns, so they must NEVER be run through a translation model: Sarvam
# translate turned "Dondakaya Vepudu" (dondakaya = ivy gourd, vepudu = fry) into
# "దోసకాయ బీఫ్" (cucumber beef) — wrong vegetable, and "beef" on a veg dish. This
# map is the source of truth; anything not in it is omitted, not guessed.
# Keys are normalized by _normalize_dish (lowercased, parentheticals/"recipe"
# stripped). To add a dish, add its verified Telugu spelling here.
TELUGU_DISH_NAMES = {
    "aratikaya vepudu": "అరటికాయ వేపుడు",
    "bendakaya pulusu": "బెండకాయ పులుసు",
    "bobbatlu": "బొబ్బట్లు",
    "chepala pulusu": "చేపల పులుసు",
    "chintapandu rasam": "చింతపండు రసం",
    "dondakaya vepudu": "దొండకాయ వేపుడు",
    "garelu": "గారెలు",
    "gongura mutton": "గోంగూర మటన్",
    "gongura pachadi": "గోంగూర పచ్చడి",
    "gutti vankaya kura": "గుత్తి వంకాయ కూర",
    "idli": "ఇడ్లీ",
    "kakarakaya vepudu": "కాకరకాయ వేపుడు",
    "kobbari pachadi": "కొబ్బరి పచ్చడి",
    "kodi vepudu": "కోడి వేపుడు",
    "mysore bonda": "మైసూర్ బోండా",
    "natu kodi pulusu": "నాటు కోడి పులుసు",
    "nimmakaya pulihora": "నిమ్మకాయ పులిహోర",
    "palakura pappu": "పాలకూర పప్పు",
    "pappu charu": "పప్పు చారు",
    "perugu annam": "పెరుగు అన్నం",
    "pesarattu": "పెసరట్టు",
    "pulihora": "పులిహోర",
    "punugulu": "పునుగులు",
    "ragi sangati": "రాగి సంగటి",
    "rava dosa": "రవ్వ దోస",
    "sakinalu": "సకినాలు",
    "sambar": "సాంబార్",
    "semiya payasam": "సేమియా పాయసం",
    "tomato pappu": "టమాటా పప్పు",
    "upma": "ఉప్మా",
    # Batch 2 (2026-07-18 bank refill) — hand-verified spellings
    "sarva pindi": "సర్వపిండి",
    "dibba rotti": "దిబ్బ రొట్టె",
    "masala dosa": "మసాలా దోస",
    "uthappam": "ఉత్తప్పం",
    "pongali": "పొంగలి",
    "hyderabadi chicken biryani": "హైదరాబాదీ చికెన్ బిర్యానీ",
    "hyderabadi veg biryani": "హైదరాబాదీ వెజ్ బిర్యానీ",
    "bagara annam": "బగారా అన్నం",
    "mamidikaya pulihora": "మామిడికాయ పులిహోర",
    "kobbari annam": "కొబ్బరి అన్నం",
    "dosakaya pappu": "దోసకాయ పప్పు",
    "mamidikaya pappu": "మామిడికాయ పప్పు",
    "gongura pappu": "గోంగూర పప్పు",
    "ulava charu": "ఉలవ చారు",
    "majjiga pulusu": "మజ్జిగ పులుసు",
    "pachi pulusu": "పచ్చి పులుసు",
    "gummadikaya pulusu": "గుమ్మడికాయ పులుసు",
    "bangaladumpa vepudu": "బంగాళదుంప వేపుడు",
    "chamadumpa vepudu": "చామదుంపల వేపుడు",
    "potlakaya vepudu": "పొట్లకాయ వేపుడు",
    "beerakaya kura": "బీరకాయ కూర",
    "munakkaya kura": "మునక్కాయ కూర",
    "aloo kurma": "ఆలూ కుర్మా",
    "bendakaya vepudu": "బెండకాయ వేపుడు",
    "kodi kura": "కోడి కూర",
    "mutton kura": "మటన్ కూర",
    "chicken 65": "చికెన్ 65",
    "royyala vepudu": "రొయ్యల వేపుడు",
    "chepala vepudu": "చేపల వేపుడు",
    "kodi guddu pulusu": "కోడిగుడ్డు పులుసు",
    "mirapakaya bajji": "మిరపకాయ బజ్జి",
    "masala vada": "మసాలా వడ",
    "chegodilu": "చేగోడీలు",
    "jantikalu": "జంతికలు",
    "ullipaya pakodi": "ఉల్లిపాయ పకోడి",
    "ariselu": "అరిసెలు",
    "poornam boorelu": "పూర్ణం బూరెలు",
    "rava laddu": "రవ్వ లడ్డు",
    "palakova": "పాలకోవా",
    "double ka meetha": "డబల్ కా మీఠా",
    "paramannam": "పరమాన్నం",
    "avakaya": "ఆవకాయ",
    "tomato pachadi": "టమాటా పచ్చడి",
    "allam pachadi": "అల్లం పచ్చడి",
    "kandi pachadi": "కంది పచ్చడి",
    "kothimeera pachadi": "కొత్తిమీర పచ్చడి",
}


def _normalize_dish(name: str) -> str:
    """Match key for TELUGU_DISH_NAMES: lowercase, drop parentheticals/'recipe'."""
    n = re.sub(r"\s*\(.*?\)\s*", " ", name.lower())
    n = re.sub(r"\brecipe\b", " ", n)
    return re.sub(r"\s+", " ", n).strip()


def telugu_dish_name(name: str) -> str | None:
    """Telugu-script dish name for bilingual SEO captions; None if unknown.

    Dish names are romanized Telugu proper nouns, so we look them up in a
    hand-verified map rather than translate them — a translation model invents
    wrong words (e.g. "beef" for "vepudu"). Unknown dishes return None and the
    caption falls back to the English-only title, which is clean and correct.
    """
    return TELUGU_DISH_NAMES.get(_normalize_dish(name))


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
    # Series posts (e.g. challenge days) open with their own line
    opener = recipe.get("vo_opener") or f"This {name} needs just {n_ing} ingredients!"
    lines = [
        opener,
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
    probe = subprocess.run([_ff(), "-i", str(path)], capture_output=True, text=True)
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", probe.stderr)
    if not m:
        return 0.0
    return float(m.group(1)) * 3600 + float(m.group(2)) * 60 + float(m.group(3))


def tts_edge(text: str, voice: str, out_path: Path) -> None:
    import edge_tts

    async def _run() -> None:
        await edge_tts.Communicate(text, voice).save(str(out_path))

    asyncio.run(_run())


def _group_words(alignment: dict) -> list[dict]:
    """Group ElevenLabs character alignment into words with local start/end (s)."""
    chars = alignment.get("characters") or []
    starts = alignment.get("character_start_times_seconds") or []
    ends = alignment.get("character_end_times_seconds") or []
    words: list[dict] = []
    cur, w_start, w_end = "", None, None
    for ch, s, e in zip(chars, starts, ends):
        if ch.isspace():
            if cur:
                words.append({"text": cur, "start": w_start, "end": w_end})
                cur = ""
            continue
        if not cur:
            w_start = s
        cur += ch
        w_end = e
    if cur:
        words.append({"text": cur, "start": w_start, "end": w_end})
    return words


def tts_elevenlabs(
    text: str, out_path: Path, previous_text: str | None = None, next_text: str | None = None
) -> list[dict]:
    """Synthesise one Telugu line in the configured voice; write audio to
    out_path and return word timings (local seconds). Uses the with-timestamps
    route on eleven_v3 (the only ElevenLabs model that speaks Telugu).

    previous_text/next_text give the model the surrounding narration so each
    line is spoken with natural prosody/continuity instead of in isolation."""
    body = {
        "text": text,
        "model_id": ELEVEN_MODEL,
        "language_code": "te",
        "voice_settings": {
            "stability": ELEVEN_STABILITY,
            "similarity_boost": 0.8,
            "use_speaker_boost": True,
        },
    }
    # previous_text/next_text give cross-line prosody but eleven_v3 rejects
    # them ("unsupported_model"); only send on models that accept them.
    if "v3" not in ELEVEN_MODEL:
        if previous_text:
            body["previous_text"] = previous_text
        if next_text:
            body["next_text"] = next_text
    resp = requests.post(
        f"{ELEVEN_BASE}/text-to-speech/{ELEVEN_VOICE}/with-timestamps",
        headers={"xi-api-key": ELEVEN_KEY, "Content-Type": "application/json"},
        params={"output_format": ELEVEN_FORMAT},
        json=body,
        timeout=180,
    )
    if not resp.ok:
        raise RuntimeError(f"ElevenLabs TTS failed: {resp.status_code} {resp.text[:300]}")
    body = resp.json()
    out_path.write_bytes(base64.b64decode(body["audio_base64"]))
    return _group_words(body.get("alignment") or {})


def _even_words(line: str, dur: float) -> list[dict]:
    """Coarse per-word timing (even split) for engines without alignment."""
    toks = line.split()
    if not toks or dur <= 0:
        return []
    step = dur / len(toks)
    return [{"text": t, "start": k * step, "end": (k + 1) * step} for k, t in enumerate(toks)]


def _fit_to_shot(path: Path, dur: float, window: float, words: list[dict]) -> tuple[Path, float, list[dict]]:
    """Only compress a segment that badly overruns its shot; a little overrun
    into the next shot is fine and sounds far more natural than speeding up.
    Speeding beyond ~1.1x reads as rushed, so cap it there."""
    if dur <= window + 1.4:
        return path, dur, words
    factor = min(1.1, dur / (window + 1.0))
    fitted = path.with_name(path.stem + "_fit" + path.suffix)
    subprocess.run(
        [_ff(), "-y", "-i", str(path), "-filter:a", f"atempo={factor:.3f}", str(fitted)],
        check=True, capture_output=True, text=True,
    )
    scaled = [{"text": w["text"], "start": w["start"] / factor, "end": w["end"] / factor} for w in words]
    return fitted, dur / factor, scaled


def _segmented_voice(lines: list[str], out_dir: Path, shot_seconds: float, engine: str) -> dict:
    """One audio segment per narration line, anchored to its shot's start time.

    Returns {"segments": [{path, start, end, words(global s)}], "lang", "engine"}.
    """
    sarvam_key = os.environ.get("SARVAM_API_KEY")
    segments = []
    for i, line in enumerate(lines):
        if not line:
            continue
        start = i * shot_seconds
        if engine == "elevenlabs":
            path = out_dir / f"vo_{i:02d}.mp3"
            # Feed the neighbouring lines so the delivery flows across shots
            prev_line = next((lines[j] for j in range(i - 1, -1, -1) if lines[j]), None)
            next_line = next((lines[j] for j in range(i + 1, len(lines)) if lines[j]), None)
            words = tts_elevenlabs(line, path, previous_text=prev_line, next_text=next_line)
        else:  # sarvam — lines are already Telugu, so skip the en->te translate
            path = out_dir / f"vo_{i:02d}.wav"
            tts_sarvam_telugu(line, sarvam_key, path)
            words = _even_words(line, audio_duration(path))
        dur = audio_duration(path)
        path, dur, words = _fit_to_shot(path, dur, shot_seconds, words)
        gwords = [{"text": w["text"], "start": start + w["start"], "end": start + w["end"]} for w in words]
        segments.append({"path": path, "start": start, "end": start + dur, "words": gwords})
    if not segments:
        raise RuntimeError("no narration segments produced")
    return {"segments": segments, "lang": "te", "engine": engine}


def _single(path: Path, lang: str, engine: str) -> dict:
    """Wrap a legacy single-blob voiceover as one segment (400ms lead, no karaoke)."""
    return {
        "segments": [{"path": path, "start": 0.4, "end": 0.4 + audio_duration(path), "words": []}],
        "lang": lang,
        "engine": engine,
    }


def _blob_voiceover(recipe: dict, handle: str, out_dir: Path, target_seconds: float | None) -> dict | None:
    """Legacy fallback: the mechanical English script, Telugu via Sarvam-translate.
    One un-timed segment; no karaoke captions.

    The VOICE stays the brand voice even here: the account's ElevenLabs
    voice (Abhi) speaks the translated blob before Sarvam's stock speaker is
    ever tried — a 2026-07-18 storyboard failure shipped a reel in a
    different (female) voice mid-stream, the most audible break possible
    for a voice-first account."""
    script = build_script(recipe, handle, target_seconds=target_seconds or 22.0)
    sarvam_key = os.environ.get("SARVAM_API_KEY")

    if sarvam_key:
        try:
            telugu = translate_to_telugu(script, sarvam_key)
        except Exception as exc:
            print(f"Sarvam translate failed, falling back to edge-tts: {exc}", file=sys.stderr)
            telugu = None
        if telugu and ELEVEN_KEY and ELEVEN_VOICE:
            try:
                path = out_dir / "voiceover.mp3"
                words = tts_elevenlabs(telugu, path)
                dur = audio_duration(path)
                if target_seconds:
                    path, dur, words = _fit_to_shot(path, dur, target_seconds, words)
                seg = _single(path, "te", "elevenlabs")
                seg["segments"][0]["words"] = [
                    {"text": w["text"], "start": 0.4 + w["start"], "end": 0.4 + w["end"]}
                    for w in words
                ]
                return seg
            except Exception as exc:
                print(f"ElevenLabs blob failed, trying Sarvam: {exc}", file=sys.stderr)
        if telugu:
            try:
                path = out_dir / "voiceover.wav"
                tts_sarvam_telugu(telugu, sarvam_key, path)
                if target_seconds:
                    dur = audio_duration(path)
                    if dur > target_seconds:
                        pace = round(min(1.5, dur / target_seconds + 0.05), 2)
                        print(f"  Voiceover {dur:.1f}s > {target_seconds:.0f}s target; retrying at pace {pace}")
                        tts_sarvam_telugu(telugu, sarvam_key, path, pace=pace)
                return _single(path, "te", "sarvam")
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
        return _single(path, "en", "edge")
    except Exception as exc:
        print(f"edge-tts voiceover failed, reel will use music only: {exc}", file=sys.stderr)
        return None


def make_voiceover(
    recipe: dict,
    handle: str,
    out_dir: Path,
    target_seconds: float | None = None,
    narration: list[str] | None = None,
    shot_seconds: float = 4.0,
) -> dict | None:
    """Create the reel voiceover as a structured result, or None.

    Result: {"segments": [{path, start, end, words}], "lang", "engine"}.

    With per-shot `narration` (Telangana-Telugu lines from storyboard), each
    line becomes its own segment anchored to `i * shot_seconds` — ElevenLabs
    first (with word timestamps for karaoke captions), then Sarvam. Without
    narration, or if both paid Telugu engines fail, falls back to the legacy
    single-blob English/Sarvam voiceover (edge-tts last).
    """
    lines = [(l or "").strip() for l in (narration or [])]
    if any(lines):
        if ELEVEN_KEY and ELEVEN_VOICE:
            try:
                return _segmented_voice(lines, out_dir, shot_seconds, "elevenlabs")
            except Exception as exc:
                print(f"ElevenLabs voiceover failed, trying Sarvam: {exc}", file=sys.stderr)
        if os.environ.get("SARVAM_API_KEY"):
            try:
                return _segmented_voice(lines, out_dir, shot_seconds, "sarvam")
            except Exception as exc:
                print(f"Sarvam segmented voiceover failed, falling back: {exc}", file=sys.stderr)

    return _blob_voiceover(recipe, handle, out_dir, target_seconds)
