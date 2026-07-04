"""AI-video reel: Seedance clips via Kie.ai, stitched with caption
overlays, voiceover, and background music into a 1080x1920 Reel.

Requires KIE_API_KEY. Clip generation is asynchronous on Kie.ai:
create a task per clip, poll until success, download the mp4s.
"""

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont

from card import FONT_CANDIDATES_BOLD, _font, _wrap

KIE_BASE = "https://api.kie.ai/api/v1"
KIE_MODEL = os.environ.get("KIE_SEEDANCE_MODEL", "bytedance/seedance-2-mini")
RESOLUTION = os.environ.get("KIE_RESOLUTION", "480p")
CLIP_SECONDS = int(os.environ.get("KIE_CLIP_SECONDS", "5"))
# AI clips per reel. 1 = hook-clip hybrid (AI opener + card stills,
# ~$0.20/day at 480p); 3 = full AI reel (~$1.40/day).
NUM_CLIPS = int(os.environ.get("KIE_CLIPS", "1"))
CARD_SECONDS = 6.0

REEL_W, REEL_H = 1080, 1920
FPS = 30
ACCENT = (232, 93, 38)


def _ffmpeg() -> str:
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


def clip_prompts(recipe: dict) -> list[str]:
    name = recipe["name"]
    area = f"{recipe['area']} " if recipe["area"] else ""
    key_ing = ", ".join(i["name"] for i in recipe["ingredients"][:4])
    return [
        (
            f"Cinematic close-up of freshly prepared {name}, {area}cuisine, "
            f"steam rising, appetizing, warm natural light, shallow depth of "
            f"field, slow camera push-in, food photography style"
        ),
        (
            f"Cooking {name} in a kitchen: {key_ing} being cooked in a pan, "
            f"sizzling, tossing, close-up of the cooking action, warm light, "
            f"appetizing food video"
        ),
        (
            f"Final plating of {name}, garnish being sprinkled on top in slow "
            f"motion, beautiful presentation on a rustic table, overhead shot "
            f"slowly rotating, mouth-watering"
        ),
    ]


def _create_task(prompt: str, key: str) -> str:
    resp = requests.post(
        f"{KIE_BASE}/jobs/createTask",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={
            "model": KIE_MODEL,
            "input": {
                "prompt": prompt,
                "duration": CLIP_SECONDS,
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


def _poll_task(task_id: str, key: str, timeout_s: int = 900) -> str:
    """Poll until the clip is ready; return the video URL."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        resp = requests.get(
            f"{KIE_BASE}/jobs/recordInfo",
            headers={"Authorization": f"Bearer {key}"},
            params={"taskId": task_id},
            timeout=60,
        )
        body = resp.json()
        data = body.get("data") or {}
        state = (data.get("state") or "").lower()
        if state in ("success", "completed"):
            blob = json.dumps(data)
            urls = re.findall(r"https://[^\"\\\s]+?\.mp4[^\"\\\s]*", blob)
            if urls:
                return urls[0]
            raise RuntimeError(f"Kie.ai task succeeded but no video URL found: {body}")
        if state in ("fail", "failed", "error"):
            raise RuntimeError(f"Kie.ai task failed: {body}")
        time.sleep(10)
    raise RuntimeError(f"Kie.ai task {task_id} timed out after {timeout_s}s")


def generate_clips(recipe: dict, key: str, out_dir: Path) -> list[Path]:
    prompts = clip_prompts(recipe)[:NUM_CLIPS]
    task_ids = [_create_task(p, key) for p in prompts]
    print(f"  Kie.ai tasks created: {task_ids}")
    paths = []
    for i, task_id in enumerate(task_ids):
        url = _poll_task(task_id, key)
        path = out_dir / f"clip{i}.mp4"
        with requests.get(url, stream=True, timeout=300) as resp:
            resp.raise_for_status()
            with path.open("wb") as fh:
                for chunk in resp.iter_content(chunk_size=1 << 20):
                    fh.write(chunk)
        print(f"  Downloaded clip {i + 1}/{len(task_ids)}")
        paths.append(path)
    return paths


def _overlay_png(lines_top: list[str], lines_bottom: list[str], out_path: Path) -> None:
    """Transparent 1080x1920 overlay with caption text bars."""
    img = Image.new("RGBA", (REEL_W, REEL_H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    top_font = _font(FONT_CANDIDATES_BOLD, 64)
    bottom_font = _font(FONT_CANDIDATES_BOLD, 44)

    def bar(lines, font, y, line_h):
        for line in lines:
            w = draw.textlength(line, font=font)
            x = (REEL_W - w) / 2
            pad = 24
            draw.rounded_rectangle(
                [x - pad, y - 10, x + w + pad, y + line_h - 4],
                radius=16,
                fill=(20, 12, 8, 200),
            )
            draw.text((x, y), line, font=font, fill=(255, 255, 255, 255))
            y += line_h + 10
        return y

    scratch = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    top_wrapped = [
        ln for text in lines_top for ln in _wrap(scratch, text, top_font, REEL_W - 160)
    ]
    bottom_wrapped = [
        ln for text in lines_bottom for ln in _wrap(scratch, text, bottom_font, REEL_W - 200)
    ]
    bar(top_wrapped, top_font, 210, 78)
    y0 = REEL_H - 320 - (len(bottom_wrapped) - 1) * 66
    y = y0
    for line in bottom_wrapped:
        w = draw.textlength(line, font=bottom_font)
        x = (REEL_W - w) / 2
        draw.rounded_rectangle(
            [x - 20, y - 8, x + w + 20, y + 52], radius=14, fill=ACCENT + (230,)
        )
        draw.text((x, y), line, font=bottom_font, fill=(255, 255, 255, 255))
        y += 66
    img.save(out_path, "PNG")


def overlay_texts(recipe: dict, handle: str) -> list[tuple[list[str], list[str]]]:
    """Hook first, value in the middle, CTA last."""
    name = recipe["name"]
    n_ing = len(recipe["ingredients"])
    n_steps = len(recipe["steps"])
    return [
        ([f"Only {n_ing} ingredients!"], [name]),
        ([f"{n_steps} easy steps"], ["Full recipe in caption"]),
        (["Save this for later!"], [f"Follow @{handle}"]),
    ]


def assemble_reel(
    clips: list[Path],
    card_paths: list[Path],
    recipe: dict,
    handle: str,
    out_path: Path,
    voiceover: Path | None,
    music: Path | None,
) -> None:
    """Stitch AI clip(s) (with hook overlays) + card stills into the reel."""
    ff = _ffmpeg()
    texts = overlay_texts(recipe, handle)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        norm = []

        # AI clips: normalize to 1080x1920/30fps and burn in the overlay
        for i, clip in enumerate(clips):
            ov = tmp_dir / f"ov{i}.png"
            _overlay_png(*texts[min(i, len(texts) - 1)], ov)
            out = tmp_dir / f"norm{i}.mp4"
            vf = (
                f"[0:v]scale={REEL_W}:{REEL_H}:force_original_aspect_ratio=increase,"
                f"crop={REEL_W}:{REEL_H},fps={FPS}[v0];[v0][1:v]overlay=0:0,format=yuv420p"
            )
            subprocess.run(
                [
                    ff, "-y", "-i", str(clip), "-i", str(ov),
                    "-filter_complex", vf,
                    "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "20",
                    str(out),
                ],
                check=True, capture_output=True, text=True,
            )
            norm.append(out)

        # Recipe cards as still segments (they carry their own text)
        for i, card in enumerate(card_paths):
            out = tmp_dir / f"card{i}.mp4"
            vf = (
                f"scale={REEL_W}:{REEL_H}:force_original_aspect_ratio=decrease,"
                f"pad={REEL_W}:{REEL_H}:(ow-iw)/2:(oh-ih)/2:color=0x24180F,"
                f"fps={FPS},format=yuv420p"
            )
            subprocess.run(
                [
                    ff, "-y", "-loop", "1", "-t", str(CARD_SECONDS), "-i", str(card),
                    "-vf", vf,
                    "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "20",
                    str(out),
                ],
                check=True, capture_output=True, text=True,
            )
            norm.append(out)

        concat_file = tmp_dir / "concat.txt"
        concat_file.write_text("\n".join(f"file '{p}'" for p in norm))
        silent = tmp_dir / "video.mp4"
        subprocess.run(
            [ff, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_file),
             "-c", "copy", str(silent)],
            check=True, capture_output=True, text=True,
        )

        # Audio: voiceover on top of quiet music, faded out, clamped to video.
        # NOTE: use an explicit -t, not -shortest — the apad'd voiceover
        # stream is infinite and -shortest hangs with copied video.
        probe = subprocess.run(
            [ff, "-i", str(silent)], capture_output=True, text=True
        )
        m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", probe.stderr)
        h, mnt, s = float(m.group(1)), float(m.group(2)), float(m.group(3))
        video_len = h * 3600 + mnt * 60 + s

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
                filters.append(f"{mix_inputs[0]}anull[aout]")
            else:
                filters.append(
                    f"{''.join(mix_inputs)}amix=inputs={len(mix_inputs)}:"
                    f"duration=first:dropout_transition=0[aout]"
                )
            cmd += [
                "-filter_complex", ";".join(filters),
                "-map", "0:v", "-map", "[aout]",
                "-c:a", "aac", "-b:a", "192k",
            ]
        else:
            cmd += ["-c:a", "copy"]
        cmd += ["-t", f"{video_len:.2f}", "-c:v", "copy", "-movflags", "+faststart", str(out_path)]
        subprocess.run(cmd, check=True, capture_output=True, text=True)


def make_ai_reel(
    recipe: dict,
    handle: str,
    card_paths: list[Path],
    out_path: Path,
    voiceover: Path | None,
    music: Path | None,
) -> None:
    key = os.environ["KIE_API_KEY"]
    with tempfile.TemporaryDirectory() as tmp:
        clips = generate_clips(recipe, key, Path(tmp))
        # With a single AI hook clip, the cards carry the recipe content
        cards = card_paths if NUM_CLIPS < 3 else []
        assemble_reel(clips, cards, recipe, handle, out_path, voiceover, music)
