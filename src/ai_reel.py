"""Full-AI recipe reel via multi-shot generations.

Backends (VIDEO_BACKEND env): "seedance" (default, via Kie.ai) or "veo"
(Veo 3.1 via the Gemini API, GEMINI_API_KEY). Veo caps generations at 8s
(2 beats) vs Seedance's 12s (3 beats); the beat grid below adapts.

Design (per researched best practices, see FEEDBACK.md and plan):
- ~24s total from TWO 12s generations, each holding 3 timestamped beats
  ("[0s] ... [4s] Cut to: ...") — cuts inside one generation are natively
  consistent, so the dish looks the same across shots.
- Clip-to-clip continuity via keyframe chaining (keyframes.py): boundary
  images K0..Kn are generated upfront and clip i runs with
  first_frame=K[i], last_frame=K[i+1], so adjacent clips share their
  boundary image exactly. Falls back to the single dish photo via @image1
  (reference_image_urls) when keyframes are unavailable (REEL_KEYFRAMES=0,
  no hero photo, no KIE_API_KEY, or generation failure).
- Per-recipe story (storyboard.py): an LLM reads the actual recipe steps
  and directs the shots — dish-specific hook, authentic preparation
  moments in real cooking order. Template beats below are the fallback.
  The kitchen set and lighting stay locked in every reel (brand look).
- Food-motion rules: camera locked or slow push-in only, food provides the
  motion, backlit steam, hands enter from frame edge, no "fast".
- Seamless loop: the last beat mirrors the hook framing (rewatches).
- No end-CTA overlay (kills completion); hook + ingredient overlays only,
  inside Instagram's safe zones.
- generate_audio=true: the clips' own sizzle/ASMR bed sits under the
  Telugu voiceover, with optional music at a whisper.
"""

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

from card import FONT_CANDIDATES_BOLD, _font, _wrap
from keyframes import generate_keyframes, state_text
from kie_client import create_task, download, get_credits, poll_task
from storyboard import plan_story

BACKEND = (os.environ.get("VIDEO_BACKEND") or "seedance").lower()
KIE_MODEL = os.environ.get("KIE_SEEDANCE_MODEL") or "bytedance/seedance-2-mini"
RESOLUTION = os.environ.get("KIE_RESOLUTION") or "480p"
TARGET_SECONDS = int(os.environ.get("REEL_SECONDS") or "24")
BEAT_SECONDS = 4
GEN_SECONDS = 8 if BACKEND == "veo" else 12  # Veo 3.1 caps at 8s/generation
BEATS_PER_GEN = GEN_SECONDS // BEAT_SECONDS
# Measured burn rates: mini@480p 9.5, seedance-2@720p 41.0; mini@720p ~19 (2x of 480p
# per Kie pricing). Set KIE_CREDITS_PER_SECOND alongside model/resolution changes so
# the budget check below doesn't start reels it can't afford to finish.
CREDITS_PER_SECOND = float(os.environ.get("KIE_CREDITS_PER_SECOND") or "19")

REEL_W, REEL_H = 1080, 1920
FPS = 30
ACCENT = (232, 93, 38)
# Instagram UI safe zones: keep text >=210px from top, >=380px from bottom
SAFE_TOP = 210
SAFE_BOTTOM = 380

# Locked brand look: one kitchen, one light, in every reel (owner decision).
# Variety comes from the per-recipe story (storyboard.py), not the set.
STYLE_BLOCK = (
    "Warm rustic South Indian kitchen, dark wood counter, brass and steel "
    "utensils, golden 45-degree side lighting, shallow depth of field, "
    "photorealistic vertical 9:16 food film."
)
NEGATIVE = "Avoid jitter, warped hands, artificial speed changes, fast motion."

# Proven appetite-hook beats, chosen by keyword match against recipe steps
HOOK_BEATS = [
    (("tadka", "temper", "mustard seeds", "curry leaves"),
     "tadka pour — mustard seeds and curry leaves crackling in hot oil poured over the dish, backlit steam"),
    (("fry", "sizzl", "roast", "saute", "sauté"),
     "close-up sizzle — the dish frying gently, oil sheen glistening, tiny bubbles"),
    (("pour", "sauce", "gravy", "curry"),
     "sauce cascade — thick glossy gravy ladled slowly over the dish"),
    (("cut", "slice", "chop"),
     "knife-cut reveal — a clean slice through the dish showing the texture inside"),
]
DEFAULT_HOOK_BEAT = (
    "garnish drop — fresh coriander sprinkled from above in slow motion, backlit steam rising"
)


def _ffmpeg() -> str:
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


DANGLING = {"for", "with", "the", "a", "an", "and", "to", "of", "in", "on", "at", "or", "until", "till", "then"}


def _action_fragment(step: str, max_words: int = 12) -> str:
    words = step.split()[:max_words]
    while words and words[-1].lower().rstrip(".,;:") in DANGLING:
        words.pop()
    frag = " ".join(words).rstrip(".,;: ")
    return frag[0].lower() + frag[1:] if frag else ""


def _pick_hook_beat(steps: list[str]) -> str:
    text = " ".join(steps).lower()
    for keywords, beat in HOOK_BEATS:
        if any(k in text for k in keywords):
            return beat
    return DEFAULT_HOOK_BEAT


def build_beats(
    recipe: dict,
    n_gens: int,
    hook_anchor: str = "@image1",
    close_anchor: str = "@image1",
    story: list[str] | None = None,
) -> list[str]:
    """Exactly n_gens * BEATS_PER_GEN beats.

    With a story (LLM-planned shot list from storyboard.plan_story) the
    beats are the story verbatim; otherwise the template below: hook,
    ingredients, actions, sizzle, loop close."""
    if story:
        return list(story)
    name = recipe["name"]
    ing_list = ", ".join(i["name"] for i in recipe["ingredients"][:6])
    steps = recipe["steps"]

    # Action beats from evenly-sampled recipe steps (used in the middle).
    # Each names its key ingredient and reuses the same bowls/setting so the
    # process visibly USES what the ingredients shot showed.
    n_action = max(1, n_gens * BEATS_PER_GEN - 5)
    stride = max(1, len(steps) // n_action)
    actions = [
        (
            f"hands entering from frame edge, {_action_fragment(steps[min(i * stride, len(steps) - 1)])}, "
            f"using the same ingredients and brass bowls from the earlier shot, one precise action"
        )
        for i in range(n_action)
    ]

    hook = (
        f"Extreme close-up of the finished {name} exactly as {hook_anchor}: backlit "
        f"steam rising, a spoon lifting one portion, glossy texture. Camera: slow push-in."
    )
    ingredients = (
        f"Overhead shot of the exact ingredients for {name} in small brass "
        f"bowls on the dark wood counter: {ing_list} — these same ingredients "
        f"are used in the following cooking shots. Camera: fixed."
    )
    sizzle = f"{_pick_hook_beat(steps)}, making {name}, continuing the same cooking process. Camera: fixed."
    loop_close = (
        f"The finished {name} exactly as {close_anchor}, same framing as the opening "
        f"shot, steam rising, garnished. Camera: slow push-in."
    )

    beats = [hook, ingredients, *[f"{a}. Camera: fixed." for a in actions], sizzle, loop_close]
    # Trim/pad to exactly n_gens * BEATS_PER_GEN, keeping first two and last two
    want = n_gens * BEATS_PER_GEN
    while len(beats) > want:
        beats.pop(2)
    while len(beats) < want:
        beats.insert(2, f"macro texture close-up of {name}, steam curling. Camera: fixed.")
    return beats


def build_generation_prompts(
    recipe: dict,
    n_gens: int,
    chained: bool = False,
    story: list[str] | None = None,
) -> list[str]:
    """n_gens multi-shot prompts; first opens with the hook, last closes the loop.

    chained=True means every clip runs with first/last keyframes, so prompts
    describe motion between the provided frames instead of anchoring to the
    single @image1/reference photo. Story beats carry their own shot text,
    so the frame anchors only apply to template beats.
    """
    if chained:
        beats = build_beats(
            recipe, n_gens,
            hook_anchor="the provided first frame",
            close_anchor="the provided last frame",
            story=story,
        )
    else:
        beats = build_beats(recipe, n_gens, story=story)
    style = STYLE_BLOCK

    prompts = []
    for g in range(n_gens):
        chunk = beats[g * BEATS_PER_GEN : (g + 1) * BEATS_PER_GEN]
        # The last frame only lands if the prompt agrees with it: without
        # this, the final timed beat describes a different shot and wins
        # over the last_frame image (verified against seedance-2-mini)
        landing = ""
        if chained and g < n_gens - 1:
            landing = (
                f" The final moment matches the provided last frame exactly: "
                f"{state_text(beats[(g + 1) * BEATS_PER_GEN])}."
            )
        if BACKEND == "veo":
            # Veo's documented multi-shot syntax is [MM:SS-MM:SS] ranges;
            # exclusions are phrased positively, not as an avoid-list
            timed = " ".join(
                f"[00:{i * BEAT_SECONDS:02d}-00:{(i + 1) * BEAT_SECONDS:02d}] {beat}"
                for i, beat in enumerate(chunk)
            )
            header = (
                "The video starts on the provided first frame and ends on the "
                "provided last frame. "
                if chained
                else "Use the reference image for the dish's exact appearance and plating. "
            )
            prompts.append(f"{header}{style} {timed}{landing} {VEO_AUDIO_LINE}")
        else:
            timed = " ".join(
                f"[{i * BEAT_SECONDS}s]{' Cut to:' if i else ''} {beat}"
                for i, beat in enumerate(chunk)
            )
            header = (
                "Animate from the provided first frame to the provided last frame. "
                if chained
                else "Use @image1 for the dish's exact appearance and plating. "
            )
            prompts.append(f"{header}{style} {timed}{landing} {NEGATIVE}")
    return prompts


def _task_input(
    prompt: str,
    ref_image: str | None,
    with_audio: bool,
    frames: tuple[str, str] | None = None,
) -> dict:
    task_input = {
        "prompt": prompt,
        "duration": GEN_SECONDS,
        "resolution": RESOLUTION,
        "aspect_ratio": "9:16",
        "generate_audio": with_audio,
    }
    if frames:
        task_input["first_frame_url"], task_input["last_frame_url"] = frames
    elif ref_image:
        task_input["reference_image_urls"] = [ref_image]
    return task_input


def generate_clips(
    prompts: list[str],
    ref_image: str | None,
    key: str,
    out_dir: Path,
    keyframes: list[str] | None = None,
) -> list[Path]:
    def _input(i: int, with_audio: bool) -> dict:
        frames = (keyframes[i], keyframes[i + 1]) if keyframes else None
        return _task_input(prompts[i], ref_image, with_audio, frames)

    # Keyframes exist upfront, so clip creation stays parallel even when chained
    task_ids = [create_task(KIE_MODEL, _input(i, True), key) for i in range(len(prompts))]
    print(f"  {len(task_ids)} Seedance generations created, waiting...", flush=True)
    paths = []
    for i, task_id in enumerate(task_ids):
        try:
            url = poll_task(task_id, key, exts="mp4")
        except RuntimeError as exc:
            # Seedance's audio safety filter false-positives on ambient
            # sound resembling speech — retry the generation silent
            if "audio" not in str(exc).lower():
                raise
            print(f"  generation {i + 1} hit the audio filter; retrying without audio", flush=True)
            retry_id = create_task(KIE_MODEL, _input(i, False), key)
            url = poll_task(retry_id, key, exts="mp4")
        path = out_dir / f"gen{i:02d}.mp4"
        download(url, path)
        print(f"  generation {i + 1}/{len(task_ids)} done", flush=True)
        paths.append(path)
    return paths


# Veo audio is prompted positively with documented labels (SFX / Ambient
# noise); speech only comes from quoted dialogue, which these prompts never
# contain. Audio can't be disabled via the Gemini API.
VEO_AUDIO_LINE = (
    "SFX: gentle sizzling of food cooking. "
    "Ambient noise: soft, warm kitchen ambience."
)


def generate_clips_veo(
    prompts: list[str],
    ref_image: str | None,
    out_dir: Path,
    keyframes: list[str] | None = None,
) -> list[Path]:
    from veo_client import build_reference, fetch_image, make_client, start_generation, wait_and_save

    client = make_client()
    # Chained mode conditions on first/last keyframes; Veo doesn't support
    # combining those with reference_images, so the dish photo only rides
    # along as an "asset" reference when there are no keyframes
    reference = None
    frames = None
    if keyframes:
        frames = [fetch_image(u) for u in keyframes]
    elif ref_image:
        reference = build_reference(ref_image)
    # Strictly sequential (create -> finish -> next): Tier 1 Veo rate limits
    # are a couple of requests/minute, so the Kie-style create-all-then-poll
    # pattern 429s on the second create and strands paid generations
    paths = []
    for i, p in enumerate(prompts):
        # The audio filter false-positives non-deterministically and rejections
        # are uncharged (googleapis/js-genai#1272) — retry the same request;
        # last attempts drop our audio line in case it is the trigger
        bare = p.replace(VEO_AUDIO_LINE, "").strip()
        variants = [p, p, p, bare, bare]
        path = out_dir / f"gen{i:02d}.mp4"
        first = frames[i] if frames else None
        last = frames[i + 1] if frames else None
        for attempt, prompt in enumerate(variants):
            try:
                op = start_generation(client, prompt, reference, GEN_SECONDS, first, last)
                wait_and_save(client, op, path)
                break
            except RuntimeError as exc:
                if "filtered" not in str(exc).lower() or attempt == len(variants) - 1:
                    raise
                print(
                    f"  generation {i + 1} hit a Veo filter; retrying "
                    f"({attempt + 2}/{len(variants)})",
                    flush=True,
                )
        print(f"  generation {i + 1}/{len(prompts)} done", flush=True)
        paths.append(path)
    return paths


def _overlay_png(
    lines_top: list[str],
    lines_bottom: list[str],
    out_path: Path,
    bottom_size: int = 46,
) -> None:
    """Transparent overlay; text kept inside IG safe zones."""
    img = Image.new("RGBA", (REEL_W, REEL_H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    top_font = _font(FONT_CANDIDATES_BOLD, 64)
    bottom_font = _font(FONT_CANDIDATES_BOLD, bottom_size)
    line_h = bottom_size + 22

    scratch = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    top_wrapped = [
        ln for t in lines_top for ln in _wrap(scratch, t, top_font, REEL_W - 200)
    ]
    bottom_wrapped = [
        ln for t in lines_bottom for ln in _wrap(scratch, t, bottom_font, REEL_W - 240)
    ]

    y = SAFE_TOP
    for line in top_wrapped:
        w = draw.textlength(line, font=top_font)
        x = (REEL_W - w) / 2
        draw.rounded_rectangle(
            [x - 24, y - 10, x + w + 24, y + 74], radius=16, fill=(20, 12, 8, 200)
        )
        draw.text((x, y), line, font=top_font, fill=(255, 255, 255, 255))
        y += 88

    y = REEL_H - SAFE_BOTTOM - len(bottom_wrapped) * line_h
    for line in bottom_wrapped:
        w = draw.textlength(line, font=bottom_font)
        x = (REEL_W - w) / 2
        draw.rounded_rectangle(
            [x - 20, y - 8, x + w + 20, y + bottom_size + 8],
            radius=14,
            fill=ACCENT + (230,),
        )
        draw.text((x, y), line, font=bottom_font, fill=(255, 255, 255, 255))
        y += line_h
    img.save(out_path, "PNG")


def _has_audio(ff: str, clip: Path) -> bool:
    probe = subprocess.run([ff, "-i", str(clip)], capture_output=True, text=True)
    return " Audio:" in probe.stderr


def assemble_reel(
    clips: list[Path],
    recipe: dict,
    handle: str,
    out_path: Path,
    voiceover: Path | None,
    music: Path | None,
) -> None:
    ff = _ffmpeg()
    n_ing = len(recipe["ingredients"])
    hook_text = recipe.get("hook") or f"Only {n_ing} ingredients!"
    # Show ALL ingredients (owner feedback: no "+N more" teasing); only
    # spill to the caption past 12 to stay inside the safe zone
    key_ing = [i["name"] for i in recipe["ingredients"][:12]]
    if n_ing > len(key_ing):
        key_ing.append(f"+ {n_ing - len(key_ing)} in caption")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        # Timed overlays: gen 1 gets hook (beat 1) + ingredients (beat 2);
        # the LAST gen gets a small follow bar on the final beat (owner
        # requirement: follow CTA at the end, kept small in the safe zone).
        ov_hook = tmp_dir / "ov_hook.png"
        _overlay_png([hook_text], [recipe["name"]], ov_hook)
        ov_ing = tmp_dir / "ov_ing.png"
        _overlay_png(["What you need:"], key_ing, ov_ing, bottom_size=40)
        ov_follow = tmp_dir / "ov_follow.png"
        _overlay_png([], [f"Follow @{handle} for daily recipes"], ov_follow)

        norm = []
        for i, clip in enumerate(clips):
            out = tmp_dir / f"norm{i:02d}.mp4"
            has_audio = _has_audio(ff, clip)
            cmd = [ff, "-y", "-i", str(clip)]
            base = (
                f"[0:v]scale={REEL_W}:{REEL_H}:force_original_aspect_ratio=increase,"
                f"crop={REEL_W}:{REEL_H},fps={FPS}"
            )
            # (png_path, enable_expr) overlays for this clip
            overlays = []
            if i == 0:
                overlays.append((ov_hook, f"lt(t,{BEAT_SECONDS})"))
                overlays.append((ov_ing, f"between(t,{BEAT_SECONDS},{2 * BEAT_SECONDS})"))
            if i == len(clips) - 1:
                overlays.append((ov_follow, f"gt(t,{GEN_SECONDS - BEAT_SECONDS})"))

            if overlays:
                for png, _ in overlays:
                    cmd += ["-i", str(png)]
                chain = f"{base}[v0]"
                cur = "v0"
                for j, (_, enable) in enumerate(overlays):
                    nxt = f"v{j + 1}"
                    chain += f";[{cur}][{j + 1}:v]overlay=0:0:enable='{enable}'[{nxt}]"
                    cur = nxt
                vf = f"{chain};[{cur}]format=yuv420p[vout]"
            else:
                vf = f"{base},format=yuv420p[vout]"

            audio_input_idx = 1 + len(overlays)
            if not has_audio:
                cmd += ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"]
                audio_map = f"{audio_input_idx}:a"
            else:
                audio_map = "0:a"
            cmd += [
                "-filter_complex", vf,
                "-map", "[vout]", "-map", audio_map,
                "-c:v", "libx264", "-preset", "medium", "-crf", "20",
                "-c:a", "aac", "-ar", "44100", "-ac", "2",
                "-t", str(GEN_SECONDS),
                str(out),
            ]
            subprocess.run(cmd, check=True, capture_output=True, text=True)
            norm.append(out)

        concat_file = tmp_dir / "concat.txt"
        concat_file.write_text("\n".join(f"file '{p}'" for p in norm))
        base_av = tmp_dir / "base.mp4"
        subprocess.run(
            [ff, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_file),
             "-c", "copy", str(base_av)],
            check=True, capture_output=True, text=True,
        )

        probe = subprocess.run([ff, "-i", str(base_av)], capture_output=True, text=True)
        m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", probe.stderr)
        video_len = float(m.group(1)) * 3600 + float(m.group(2)) * 60 + float(m.group(3))

        # Mix: sizzle bed (from clips) + voiceover + optional whisper of music.
        # Explicit -t, never -shortest (apad'd voiceover is infinite).
        cmd = [ff, "-y", "-i", str(base_av)]
        filters = ["[0:a]volume=0.5[siz]"]
        mix = ["[siz]"]
        idx = 1
        if voiceover is not None:
            cmd += ["-i", str(voiceover)]
            filters.append(f"[{idx}:a]adelay=400|400,apad[vo]")
            mix.append("[vo]")
            idx += 1
        if music is not None:
            cmd += ["-stream_loop", "-1", "-i", str(music)]
            filters.append(f"[{idx}:a]volume=0.06[mu]")
            mix.append("[mu]")
            idx += 1
        filters.append(
            f"{''.join(mix)}amix=inputs={len(mix)}:duration=first:"
            f"dropout_transition=0,afade=t=out:st={max(video_len - 1.2, 0)}:d=1.2[aout]"
        )
        cmd += [
            "-filter_complex", ";".join(filters),
            "-map", "0:v", "-map", "[aout]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            "-t", f"{video_len:.2f}",
            "-movflags", "+faststart", str(out_path),
        ]
        subprocess.run(cmd, check=True, capture_output=True, text=True)


def make_ai_reel(
    recipe: dict,
    handle: str,
    out_path: Path,
    voiceover: Path | None,
    music: Path | None,
) -> None:
    n_gens = max(1, round(TARGET_SECONDS / GEN_SECONDS))

    key = None
    if BACKEND != "veo":
        # Kie exposes a credit balance; Gemini billing has no equivalent check.
        # Keyframes add a few image generations per reel on top — cents next
        # to the video burn, so the gate only budgets video seconds.
        key = os.environ["KIE_API_KEY"]
        per_gen = GEN_SECONDS * CREDITS_PER_SECOND
        balance = get_credits(key)
        affordable = int(balance // per_gen)
        if affordable < 1:
            raise RuntimeError(
                f"Kie.ai balance too low: {balance:.0f} credits (~{per_gen:.0f}/generation). Top up."
            )
        if affordable < n_gens:
            print(f"  Credits low ({balance:.0f}): {affordable} generation(s) only", flush=True)
            n_gens = affordable
        if balance - n_gens * per_gen < 2 * n_gens * per_gen:
            print(f"  WARNING: Kie credits low ({balance:.0f}) — under ~2 days of reels left. Top up soon.", flush=True)

    ref_image = recipe.get("thumb") or None
    # Per-recipe story: the shot list comes from how the dish is actually
    # prepared (one Gemini flash call); None falls back to template beats
    story = plan_story(recipe, n_gens * BEATS_PER_GEN, STYLE_BLOCK)
    if story:
        print(f"  story planned: {len(story)} shots", flush=True)
    # Keyframe chain (K0..Kn) for first/last-frame conditioning; images are
    # generated on Kie regardless of video backend. Any failure falls back
    # to the single-reference-image path rather than killing the reel.
    keyframes = None
    kie_key = key or os.environ.get("KIE_API_KEY")
    # n_gens < 2 has no clip boundary to sync (and beat trimming drops the
    # loop-close beat the final keyframe is aligned with) — skip chaining
    if n_gens >= 2 and ref_image and kie_key and (os.environ.get("REEL_KEYFRAMES") or "1") != "0":
        try:
            beats = build_beats(recipe, n_gens, story=story)
            keyframes = generate_keyframes(
                recipe, beats, BEATS_PER_GEN, n_gens, STYLE_BLOCK, ref_image, kie_key
            )
            print(f"  {len(keyframes)} boundary keyframes generated", flush=True)
        except Exception as exc:
            print(f"  keyframes failed ({exc}); using single reference image", flush=True)

    prompts = build_generation_prompts(
        recipe, n_gens, chained=keyframes is not None, story=story
    )
    with tempfile.TemporaryDirectory() as tmp:
        if BACKEND == "veo":
            clips = generate_clips_veo(prompts, ref_image, Path(tmp), keyframes)
        else:
            clips = generate_clips(prompts, ref_image, key, Path(tmp), keyframes)
        assemble_reel(clips, recipe, handle, out_path, voiceover, music)
