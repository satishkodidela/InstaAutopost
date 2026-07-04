"""Full-AI recipe reel: prompt-structured cut shots via Seedance (Kie.ai),
stitched into a 1080x1920 Reel with voiceover and music.

Shot structure (standard recipe-reel arc, ~44s total at 5s cuts):
  1. Hook       — finished dish, steam, dramatic close-up (+ text hook)
  2. Ingredients— everything laid out on the counter
  3..N-1        — cooking-action cuts derived from the recipe steps
  N. Reveal     — final plating / garnish (+ follow CTA overlay)

Cost guard: checks the Kie.ai credit balance up front and shrinks the
shot list to fit; raises if even a minimal reel is unaffordable.
"""

import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import requests
from PIL import Image, ImageDraw

from card import FONT_CANDIDATES_BOLD, _font, _wrap

KIE_BASE = "https://api.kie.ai/api/v1"
KIE_MODEL = os.environ.get("KIE_SEEDANCE_MODEL", "bytedance/seedance-2-mini")
RESOLUTION = os.environ.get("KIE_RESOLUTION", "480p")
TARGET_SECONDS = int(os.environ.get("REEL_SECONDS", "44"))
SHOT_SECONDS = 5
CREDITS_PER_SECOND = 9.5  # measured for seedance-2-mini @480p
MIN_SHOTS = 5

REEL_W, REEL_H = 1080, 1920
FPS = 30
ACCENT = (232, 93, 38)

STYLE = (
    "vertical 9:16 food reel, cinematic, warm natural kitchen light, "
    "shallow depth of field, appetizing, high detail, smooth camera motion"
)


def _ffmpeg() -> str:
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


def _headers(key: str) -> dict:
    return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}


def get_credits(key: str) -> float:
    resp = requests.get(f"{KIE_BASE}/chat/credit", headers=_headers(key), timeout=30)
    body = resp.json()
    if body.get("code") != 200 or body.get("data") is None:
        raise RuntimeError(f"Kie.ai credit check failed: {body}")
    return float(body["data"])


def _action_fragment(step: str, max_words: int = 14) -> str:
    frag = " ".join(step.split()[:max_words]).rstrip(".,;: ")
    return frag[0].lower() + frag[1:] if frag else ""


def build_shot_list(recipe: dict, n_shots: int) -> list[str]:
    """Hook + ingredients + step-action cuts + final reveal."""
    name = recipe["name"]
    area = f"{recipe['area']} " if recipe["area"] else ""
    ing_list = ", ".join(i["name"] for i in recipe["ingredients"][:6])

    hook = (
        f"Extreme close-up of freshly made {name}, {area}dish, steam rising, "
        f"slow camera push-in, mouth-watering, {STYLE}"
    )
    ingredients = (
        f"Overhead shot of fresh ingredients for {name} laid out on a rustic "
        f"wooden counter: {ing_list}, camera slowly gliding across, {STYLE}"
    )
    reveal = (
        f"Final plating of {name}, garnish falling in slow motion, beautiful "
        f"presentation, slow rotating shot, {STYLE}"
    )

    n_action = max(1, n_shots - 3)
    steps = recipe["steps"]
    if len(steps) <= n_action:
        picks = steps
    else:
        stride = len(steps) / n_action
        picks = [steps[int(i * stride)] for i in range(n_action)]
    actions = [
        (
            f"Close-up of hands cooking: {_action_fragment(s)}, making {name}, "
            f"fast-paced cooking action, {STYLE}"
        )
        for s in picks
    ]

    # Recipes with few steps: pad with beauty shots to hit the target length
    extras = [
        f"Macro texture shot of {name}, fork lifting a bite, steam curling up, {STYLE}",
        f"Hands sprinkling fresh herbs and seasoning over {name} in a pan, {STYLE}",
        f"{name} served on a table spread with drinks and sides, cozy dinner scene, {STYLE}",
        f"Side angle of {name} being lifted from the pan, dripping and delicious, {STYLE}",
    ]
    shots = [hook, ingredients, *actions]
    for extra in extras:
        if len(shots) >= n_shots - 1:
            break
        shots.append(extra)
    return [*shots, reveal]


def _create_task(prompt: str, key: str) -> str:
    resp = requests.post(
        f"{KIE_BASE}/jobs/createTask",
        headers=_headers(key),
        json={
            "model": KIE_MODEL,
            "input": {
                "prompt": prompt,
                "duration": SHOT_SECONDS,
                "resolution": RESOLUTION,
                "aspect_ratio": "9:16",
            },
        },
        timeout=60,
    )
    body = resp.json()
    task_id = (body.get("data") or {}).get("taskId") or body.get("taskId")
    if not resp.ok or not task_id:
        raise RuntimeError(f"Kie.ai createTask failed: {resp.status_code} {body}")
    return task_id


def _poll_task(task_id: str, key: str, timeout_s: int = 1200) -> str:
    import json as _json

    deadline = time.time() + timeout_s
    while time.time() < deadline:
        resp = requests.get(
            f"{KIE_BASE}/jobs/recordInfo",
            headers=_headers(key),
            params={"taskId": task_id},
            timeout=60,
        )
        body = resp.json()
        data = body.get("data") or {}
        state = (data.get("state") or "").lower()
        if state in ("success", "completed"):
            blob = _json.dumps(data)
            urls = re.findall(r"https://[^\"\\\s]+?\.mp4[^\"\\\s]*", blob)
            if urls:
                return urls[0]
            raise RuntimeError(f"Kie.ai task succeeded but no video URL found: {body}")
        if state in ("fail", "failed", "error"):
            raise RuntimeError(f"Kie.ai task failed: {body}")
        time.sleep(10)
    raise RuntimeError(f"Kie.ai task {task_id} timed out after {timeout_s}s")


def generate_shots(prompts: list[str], key: str, out_dir: Path) -> list[Path]:
    """Create all tasks up front (they render in parallel), then collect."""
    task_ids = [_create_task(p, key) for p in prompts]
    print(f"  {len(task_ids)} Seedance tasks created, waiting for renders...", flush=True)
    paths = []
    for i, task_id in enumerate(task_ids):
        url = _poll_task(task_id, key)
        path = out_dir / f"shot{i:02d}.mp4"
        with requests.get(url, stream=True, timeout=300) as resp:
            resp.raise_for_status()
            with path.open("wb") as fh:
                for chunk in resp.iter_content(chunk_size=1 << 20):
                    fh.write(chunk)
        print(f"  shot {i + 1}/{len(task_ids)} done", flush=True)
        paths.append(path)
    return paths


def _overlay_png(lines_top: list[str], lines_bottom: list[str], out_path: Path) -> None:
    """Transparent 1080x1920 overlay with caption text bars."""
    img = Image.new("RGBA", (REEL_W, REEL_H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    top_font = _font(FONT_CANDIDATES_BOLD, 64)
    bottom_font = _font(FONT_CANDIDATES_BOLD, 44)

    scratch = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    top_wrapped = [
        ln for text in lines_top for ln in _wrap(scratch, text, top_font, REEL_W - 160)
    ]
    bottom_wrapped = [
        ln for text in lines_bottom for ln in _wrap(scratch, text, bottom_font, REEL_W - 200)
    ]

    y = 210
    for line in top_wrapped:
        w = draw.textlength(line, font=top_font)
        x = (REEL_W - w) / 2
        draw.rounded_rectangle(
            [x - 24, y - 10, x + w + 24, y + 74], radius=16, fill=(20, 12, 8, 200)
        )
        draw.text((x, y), line, font=top_font, fill=(255, 255, 255, 255))
        y += 88

    y = REEL_H - 320 - (len(bottom_wrapped) - 1) * 66
    for line in bottom_wrapped:
        w = draw.textlength(line, font=bottom_font)
        x = (REEL_W - w) / 2
        draw.rounded_rectangle(
            [x - 20, y - 8, x + w + 20, y + 52], radius=14, fill=ACCENT + (230,)
        )
        draw.text((x, y), line, font=bottom_font, fill=(255, 255, 255, 255))
        y += 66
    img.save(out_path, "PNG")


def assemble_reel(
    shots: list[Path],
    recipe: dict,
    handle: str,
    out_path: Path,
    voiceover: Path | None,
    music: Path | None,
) -> None:
    ff = _ffmpeg()
    n_ing = len(recipe["ingredients"])
    overlays = {
        0: ([f"Only {n_ing} ingredients!"], [recipe["name"]]),
        len(shots) - 1: (["Save this for later!"], [f"Follow @{handle}"]),
    }

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        norm = []
        for i, shot in enumerate(shots):
            out = tmp_dir / f"norm{i:02d}.mp4"
            cmd = [ff, "-y", "-i", str(shot)]
            base = (
                f"[0:v]scale={REEL_W}:{REEL_H}:force_original_aspect_ratio=increase,"
                f"crop={REEL_W}:{REEL_H},fps={FPS}"
            )
            if i in overlays:
                ov = tmp_dir / f"ov{i}.png"
                _overlay_png(*overlays[i], ov)
                cmd += ["-i", str(ov)]
                vf = f"{base}[v0];[v0][1:v]overlay=0:0,format=yuv420p"
            else:
                vf = f"{base},format=yuv420p"
            cmd += [
                "-filter_complex", vf, "-an",
                "-c:v", "libx264", "-preset", "medium", "-crf", "20", str(out),
            ]
            subprocess.run(cmd, check=True, capture_output=True, text=True)
            norm.append(out)

        concat_file = tmp_dir / "concat.txt"
        concat_file.write_text("\n".join(f"file '{p}'" for p in norm))
        silent = tmp_dir / "video.mp4"
        subprocess.run(
            [ff, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_file),
             "-c", "copy", str(silent)],
            check=True, capture_output=True, text=True,
        )

        probe = subprocess.run([ff, "-i", str(silent)], capture_output=True, text=True)
        m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", probe.stderr)
        video_len = float(m.group(1)) * 3600 + float(m.group(2)) * 60 + float(m.group(3))

        # Voiceover over quiet music, faded out, clamped with explicit -t
        # (the apad'd voiceover stream is infinite; -shortest would hang)
        cmd = [ff, "-y", "-i", str(silent)]
        filters, mix_inputs = [], []
        idx = 1
        if voiceover is not None:
            cmd += ["-i", str(voiceover)]
            filters.append(f"[{idx}:a]adelay=600|600,apad[vo]")
            mix_inputs.append("[vo]")
            idx += 1
        if music is not None:
            cmd += ["-stream_loop", "-1", "-i", str(music)]
            vol = 0.12 if voiceover is not None else 0.6
            filters.append(f"[{idx}:a]volume={vol}[mu]")
            mix_inputs.append("[mu]")
            idx += 1

        if mix_inputs:
            if len(mix_inputs) == 1:
                filters.append(f"{mix_inputs[0]}anull[amixed]")
            else:
                filters.append(
                    f"{''.join(mix_inputs)}amix=inputs={len(mix_inputs)}:"
                    f"duration=first:dropout_transition=0[amixed]"
                )
            filters.append(f"[amixed]afade=t=out:st={max(video_len - 1.5, 0)}:d=1.5[aout]")
            cmd += [
                "-filter_complex", ";".join(filters),
                "-map", "0:v", "-map", "[aout]",
                "-c:a", "aac", "-b:a", "192k",
            ]
        else:
            cmd += ["-an"]
        cmd += ["-t", f"{video_len:.2f}", "-c:v", "copy",
                "-movflags", "+faststart", str(out_path)]
        subprocess.run(cmd, check=True, capture_output=True, text=True)


def make_ai_reel(
    recipe: dict,
    handle: str,
    out_path: Path,
    voiceover: Path | None,
    music: Path | None,
) -> None:
    key = os.environ["KIE_API_KEY"]

    n_shots = max(MIN_SHOTS, round(TARGET_SECONDS / SHOT_SECONDS))
    balance = get_credits(key)
    per_shot = SHOT_SECONDS * CREDITS_PER_SECOND
    affordable = int(balance // per_shot)
    if affordable < MIN_SHOTS:
        raise RuntimeError(
            f"Kie.ai balance too low for a reel: {balance:.0f} credits "
            f"(~{per_shot:.0f}/shot, need >= {MIN_SHOTS} shots). Top up."
        )
    if affordable < n_shots:
        print(f"  Credits low ({balance:.0f}): trimming reel to {affordable} shots", flush=True)
        n_shots = affordable

    prompts = build_shot_list(recipe, n_shots)
    with tempfile.TemporaryDirectory() as tmp:
        shots = generate_shots(prompts, key, Path(tmp))
        assemble_reel(shots, recipe, handle, out_path, voiceover, music)
