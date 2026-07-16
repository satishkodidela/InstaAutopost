"""Publish today's generated post to Instagram via the Graph API.

Posts a Reel when posts/YYYY-MM-DD.mp4 exists, a carousel when multiple
cards exist for today, and a single image otherwise.

Requires env vars:
  IG_USER_ID        - Instagram professional account user ID
  IG_ACCESS_TOKEN   - long-lived access token
  GITHUB_REPOSITORY - owner/repo (set automatically in GitHub Actions);
                      used to build the public raw.githubusercontent.com
                      image URLs. The repo must be public.

The images must already be committed and pushed (the workflow does this
before running this script).
"""

import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

API_BASE = "https://graph.instagram.com/v23.0"


def thumb_offset_ms(video: Path) -> int | None:
    """Cover-frame offset for the Reel container, in milliseconds.

    Without it Instagram covers the reel with frame 1, and the profile
    grid's 3:4 centre crop slices the hook headline in half. Aim at the
    serving/payoff beat — 6s before the end lands mid-way through the
    second-to-last 4s shot. Returns None if the video can't be probed
    (the container is then created without an offset, as before).
    """
    ff = shutil.which("ffmpeg")
    if not ff:
        try:
            import imageio_ffmpeg

            ff = imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            return None
    probe = subprocess.run([ff, "-i", str(video)], capture_output=True, text=True)
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", probe.stderr)
    if not m:
        return None
    dur = float(m.group(1)) * 3600 + float(m.group(2)) * 60 + float(m.group(3))
    return int(max(dur - 6.0, 0) * 1000)


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        print(f"Missing required env var: {name}", file=sys.stderr)
        sys.exit(1)
    return value


def wait_for_url(url: str, attempts: int = 12, delay: int = 10) -> None:
    """Wait until the raw GitHub URL is publicly reachable."""
    for _ in range(attempts):
        try:
            if requests.head(url, timeout=15).status_code == 200:
                return
        except requests.RequestException:
            pass
        time.sleep(delay)
    print(f"Image URL never became reachable: {url}", file=sys.stderr)
    sys.exit(1)


def wait_for_container(creation_id: str, token: str, attempts: int = 60, delay: int = 5) -> None:
    for _ in range(attempts):
        resp = requests.get(
            f"{API_BASE}/{creation_id}",
            params={"fields": "status_code", "access_token": token},
            timeout=30,
        ).json()
        status = resp.get("status_code")
        if status == "FINISHED":
            return
        if status == "ERROR":
            print(f"Media container failed: {resp}", file=sys.stderr)
            sys.exit(1)
        time.sleep(delay)
    print("Timed out waiting for media container.", file=sys.stderr)
    sys.exit(1)


def create_container(ig_user_id: str, token: str, data: dict) -> str:
    resp = requests.post(
        f"{API_BASE}/{ig_user_id}/media",
        data={**data, "access_token": token},
        timeout=60,
    ).json()
    creation_id = resp.get("id")
    if not creation_id:
        print(f"Failed to create media container: {resp}", file=sys.stderr)
        sys.exit(1)
    wait_for_container(creation_id, token)
    return creation_id


def publish(ig_user_id: str, token: str, creation_id: str) -> None:
    print("Publishing...")
    resp = requests.post(
        f"{API_BASE}/{ig_user_id}/media_publish",
        data={"creation_id": creation_id, "access_token": token},
        timeout=60,
    ).json()
    media_id = resp.get("id")
    if not media_id:
        print(f"Failed to publish: {resp}", file=sys.stderr)
        sys.exit(1)
    print(f"Published! Media ID: {media_id}")


def main() -> None:
    ig_user_id = require_env("IG_USER_ID")
    token = require_env("IG_ACCESS_TOKEN")
    repo = require_env("GITHUB_REPOSITORY")
    branch = os.environ.get("GITHUB_REF_NAME", "main")

    date_str = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%Y-%m-%d")
    posts_dir = Path(__file__).resolve().parent.parent / "posts"
    caption_path = posts_dir / f"{date_str}.txt"
    video = posts_dir / f"{date_str}.mp4"
    images = sorted(posts_dir.glob(f"{date_str}-*.jpg")) or [posts_dir / f"{date_str}.jpg"]
    images = [p for p in images if p.exists()]

    if (not images and not video.exists()) or not caption_path.exists():
        print(f"No generated post found for {date_str}. Run generate.py first.", file=sys.stderr)
        sys.exit(1)

    caption = caption_path.read_text(encoding="utf-8")

    def raw_url(name: str) -> str:
        return f"https://raw.githubusercontent.com/{repo}/{branch}/posts/{name}"

    if video.exists():
        video_url = raw_url(video.name)
        print(f"Waiting for video to be reachable: {video_url}")
        wait_for_url(video_url)
        print("Creating Reel container...")
        data = {
            "media_type": "REELS",
            "video_url": video_url,
            "caption": caption,
            "share_to_feed": "true",
        }
        offset = thumb_offset_ms(video)
        if offset is not None:
            data["thumb_offset"] = str(offset)
        creation_id = create_container(ig_user_id, token, data)
        publish(ig_user_id, token, creation_id)
        return

    image_urls = [raw_url(p.name) for p in images]

    for url in image_urls:
        print(f"Waiting for image to be reachable: {url}")
        wait_for_url(url)

    if len(image_urls) == 1:
        print("Creating single-image container...")
        creation_id = create_container(
            ig_user_id, token, {"image_url": image_urls[0], "caption": caption}
        )
    else:
        print(f"Creating {len(image_urls)} carousel item containers...")
        children = [
            create_container(
                ig_user_id, token, {"image_url": url, "is_carousel_item": "true"}
            )
            for url in image_urls
        ]
        print("Creating carousel container...")
        creation_id = create_container(
            ig_user_id,
            token,
            {
                "media_type": "CAROUSEL",
                "children": ",".join(children),
                "caption": caption,
            },
        )

    publish(ig_user_id, token, creation_id)


if __name__ == "__main__":
    main()
