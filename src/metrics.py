"""Pull Instagram insights for recent posts into data/metrics.json.

Run weekly by .github/workflows/metrics.yml (or manually). Answers
"is this content working?" with real numbers: views, reach, likes,
comments, saves, shares per post — reels vs carousels.
"""

import json
import os
import sys
from pathlib import Path

import requests

API_BASE = "https://graph.instagram.com/v23.0"

REEL_METRICS = "views,reach,likes,comments,saved,shares,total_interactions"
FEED_METRICS = "views,reach,likes,comments,saved,shares"
BASIC_METRICS = "reach,likes,comments,saved,shares"


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        print(f"Missing required env var: {name}", file=sys.stderr)
        sys.exit(1)
    return value


def get_insights(media_id: str, product: str, token: str) -> dict:
    metric_sets = [REEL_METRICS if product == "REELS" else FEED_METRICS, BASIC_METRICS]
    for metrics in metric_sets:
        resp = requests.get(
            f"{API_BASE}/{media_id}/insights",
            params={"metric": metrics, "access_token": token},
            timeout=30,
        ).json()
        if "data" in resp:
            return {
                item["name"]: (item.get("values") or [{}])[0].get("value", 0)
                for item in resp["data"]
            }
    print(f"  insights unavailable for {media_id}: {resp}", file=sys.stderr)
    return {}


def main() -> None:
    ig_user_id = require_env("IG_USER_ID")
    token = require_env("IG_ACCESS_TOKEN")

    resp = requests.get(
        f"{API_BASE}/{ig_user_id}/media",
        params={
            "fields": "id,caption,media_type,media_product_type,timestamp,permalink",
            "limit": 25,
            "access_token": token,
        },
        timeout=30,
    ).json()
    media = resp.get("data")
    if media is None:
        print(f"Failed to list media: {resp}", file=sys.stderr)
        sys.exit(1)

    out_path = Path(__file__).resolve().parent.parent / "data" / "metrics.json"
    existing = json.loads(out_path.read_text()) if out_path.exists() else {}

    for m in media:
        product = m.get("media_product_type", "")
        insights = get_insights(m["id"], product, token)
        caption_head = (m.get("caption") or "").split("\n")[0][:80]
        existing[m["id"]] = {
            "date": (m.get("timestamp") or "")[:10],
            "type": product or m.get("media_type", ""),
            "title": caption_head,
            "permalink": m.get("permalink", ""),
            "insights": insights,
        }

    out_path.parent.mkdir(exist_ok=True)
    out_path.write_text(json.dumps(existing, indent=2, ensure_ascii=False) + "\n")

    rows = sorted(existing.values(), key=lambda r: r["date"], reverse=True)
    print(f"{'date':<12}{'type':<10}{'views':>7}{'reach':>7}{'likes':>6}"
          f"{'saves':>6}{'shares':>7}  title")
    for r in rows[:15]:
        i = r["insights"]
        print(f"{r['date']:<12}{r['type']:<10}{i.get('views', '-'):>7}"
              f"{i.get('reach', '-'):>7}{i.get('likes', '-'):>6}"
              f"{i.get('saved', '-'):>6}{i.get('shares', '-'):>7}  {r['title'][:40]}")


if __name__ == "__main__":
    main()
