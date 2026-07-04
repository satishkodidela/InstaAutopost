"""One-off local test: publish today's generated cards to Instagram.

Unlike publish.py (which uses raw.githubusercontent.com URLs), this
uploads the images to tmpfiles.org — a temporary public host whose links
expire after ~60 minutes — so you can test before the repo is on GitHub.

Reads IG_ACCESS_TOKEN (required) and IG_USER_ID (optional, looked up via
/me if missing) from the environment or from a .env file in the repo root.

Usage:
    python src/test_post.py           # publish today's cards as a test
"""

import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from publish import API_BASE, create_container, publish

ROOT = Path(__file__).resolve().parent.parent


def load_dotenv() -> None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def upload_temp(path: Path) -> str:
    """Upload to tmpfiles.org and return the direct-download URL."""
    mime = "video/mp4" if path.suffix == ".mp4" else "image/jpeg"
    with path.open("rb") as fh:
        resp = requests.post(
            "https://tmpfiles.org/api/v1/upload",
            files={"file": (path.name, fh, mime)},
            timeout=180,
        )
    resp.raise_for_status()
    url = resp.json()["data"]["url"]
    # Page URL -> direct file URL Instagram can fetch
    return url.replace("tmpfiles.org/", "tmpfiles.org/dl/")


def main() -> None:
    load_dotenv()

    token = os.environ.get("IG_ACCESS_TOKEN")
    if not token:
        print(
            "Set IG_ACCESS_TOKEN in the environment or in a .env file "
            "in the repo root (see .env.example).",
            file=sys.stderr,
        )
        sys.exit(1)

    ig_user_id = os.environ.get("IG_USER_ID")
    if not ig_user_id:
        resp = requests.get(
            f"{API_BASE.rsplit('/', 1)[0]}/me",
            params={"fields": "user_id,username", "access_token": token},
            timeout=30,
        ).json()
        ig_user_id = str(resp.get("user_id") or resp.get("id") or "")
        if not ig_user_id:
            print(f"Could not resolve IG user id from token: {resp}", file=sys.stderr)
            sys.exit(1)
        print(f"Posting as @{resp.get('username', '?')} (id {ig_user_id})")

    date_str = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%Y-%m-%d")
    posts_dir = ROOT / "posts"
    video = posts_dir / f"{date_str}.mp4"
    images = sorted(posts_dir.glob(f"{date_str}-*.jpg"))
    caption_path = posts_dir / f"{date_str}.txt"
    if (not images and not video.exists()) or not caption_path.exists():
        print(f"No generated post for {date_str}. Run src/generate.py first.", file=sys.stderr)
        sys.exit(1)

    caption = caption_path.read_text(encoding="utf-8")

    if video.exists():
        print("Uploading video to temporary host...")
        video_url = upload_temp(video)
        print(f"  {video.name} -> {video_url}")
        print("Creating Reel container (video processing can take a minute)...")
        creation_id = create_container(
            ig_user_id,
            token,
            {
                "media_type": "REELS",
                "video_url": video_url,
                "caption": caption,
                "share_to_feed": "true",
            },
        )
        publish(ig_user_id, token, creation_id)
        return

    print(f"Uploading {len(images)} images to temporary host...")
    urls = []
    for path in images:
        url = upload_temp(path)
        print(f"  {path.name} -> {url}")
        urls.append(url)

    if len(urls) == 1:
        creation_id = create_container(
            ig_user_id, token, {"image_url": urls[0], "caption": caption}
        )
    else:
        print("Creating carousel item containers...")
        children = [
            create_container(ig_user_id, token, {"image_url": u, "is_carousel_item": "true"})
            for u in urls
        ]
        print("Creating carousel container...")
        creation_id = create_container(
            ig_user_id,
            token,
            {"media_type": "CAROUSEL", "children": ",".join(children), "caption": caption},
        )

    publish(ig_user_id, token, creation_id)
    print("Check your Instagram feed.")


if __name__ == "__main__":
    main()
