"""Build a 1080x1920 Reel (slideshow video) from the day's cards.

Frames: each 1080x1350 card centered on a blurred, darkened full-screen
version of the dish photo. Optional background music from assets/music/
(royalty-free tracks the account owner supplies), faded out at the end.
"""

import io
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageEnhance, ImageFilter

REEL_W, REEL_H = 1080, 1920

COVER_SECONDS = 3.0
CARD_SECONDS = 7.0
FOLLOW_SECONDS = 3.0
FPS = 30


def _ffmpeg() -> str:
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


def _background(photo: bytes) -> Image.Image:
    bg = Image.open(io.BytesIO(photo)).convert("RGB")
    scale = max(REEL_W / bg.width, REEL_H / bg.height)
    bg = bg.resize((round(bg.width * scale), round(bg.height * scale)), Image.LANCZOS)
    left = (bg.width - REEL_W) // 2
    top = (bg.height - REEL_H) // 2
    bg = bg.crop((left, top, left + REEL_W, top + REEL_H))
    bg = bg.filter(ImageFilter.GaussianBlur(30))
    return ImageEnhance.Brightness(bg).enhance(0.4)


def build_reel(
    card_paths: list[Path],
    photo: bytes,
    out_path: Path,
    music_path: Path | None = None,
) -> None:
    bg = _background(photo)

    durations = (
        [COVER_SECONDS]
        + [CARD_SECONDS] * (len(card_paths) - 2)
        + [FOLLOW_SECONDS]
    )
    total = sum(durations)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        concat_lines = []
        for i, card_path in enumerate(card_paths):
            frame = bg.copy()
            card = Image.open(card_path).convert("RGB")
            frame.paste(card, ((REEL_W - card.width) // 2, (REEL_H - card.height) // 2))
            frame_file = tmp_dir / f"frame{i}.png"
            frame.save(frame_file, "PNG")
            concat_lines.append(f"file '{frame_file}'")
            concat_lines.append(f"duration {durations[i]}")
        # concat demuxer needs the last frame repeated without a duration
        concat_lines.append(f"file '{tmp_dir / f'frame{len(card_paths) - 1}.png'}'")
        concat_file = tmp_dir / "frames.txt"
        concat_file.write_text("\n".join(concat_lines))

        cmd = [_ffmpeg(), "-y", "-f", "concat", "-safe", "0", "-i", str(concat_file)]
        if music_path is not None:
            cmd += ["-stream_loop", "-1", "-i", str(music_path)]
        cmd += [
            "-t", str(total),
            "-vf", f"fps={FPS},format=yuv420p",
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", "20",
            "-r", str(FPS),
        ]
        if music_path is not None:
            cmd += [
                "-c:a", "aac",
                "-b:a", "192k",
                "-af", f"afade=t=out:st={max(total - 1.5, 0)}:d=1.5",
                "-shortest",
            ]
        cmd += ["-movflags", "+faststart", str(out_path)]

        subprocess.run(cmd, check=True, capture_output=True, text=True)
