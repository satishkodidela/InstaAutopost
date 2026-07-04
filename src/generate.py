"""Generate today's post: fetch headlines, render the card, write the caption.

Outputs posts/YYYY-MM-DD.jpg and posts/YYYY-MM-DD.txt (dated in IST).
"""

import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from card import make_card
from news import fetch_headlines

HASHTAGS = (
    "#IndiaNews #DailyNews #NewsUpdate #BreakingNews #India "
    "#CurrentAffairs #NewsHighlights #TodayNews"
)


def build_caption(headlines: list[dict], date_label: str) -> str:
    lines = [f"🇮🇳 India Daily News — {date_label}", ""]
    for i, item in enumerate(headlines, start=1):
        lines.append(f"{i}. {item['title']} ({item['source']})")
    lines += [
        "",
        "Follow for daily news highlights! 📰",
        "",
        HASHTAGS,
    ]
    return "\n".join(lines)


def main() -> None:
    now_ist = datetime.now(ZoneInfo("Asia/Kolkata"))
    date_str = now_ist.strftime("%Y-%m-%d")
    date_label = now_ist.strftime("%A, %d %B %Y")

    headlines = fetch_headlines(count=5)
    if len(headlines) < 3:
        print(f"Only {len(headlines)} headlines fetched; aborting.", file=sys.stderr)
        sys.exit(1)

    posts_dir = Path(__file__).resolve().parent.parent / "posts"
    posts_dir.mkdir(exist_ok=True)

    image_path = posts_dir / f"{date_str}.jpg"
    caption_path = posts_dir / f"{date_str}.txt"

    make_card(headlines, date_label, str(image_path))
    caption_path.write_text(build_caption(headlines, date_label), encoding="utf-8")

    print(f"Generated {image_path.name} with {len(headlines)} headlines:")
    for item in headlines:
        print(f"  - {item['title']} ({item['source']})")


if __name__ == "__main__":
    main()
