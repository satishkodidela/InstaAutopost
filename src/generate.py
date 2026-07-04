"""Generate today's carousel post: fetch headlines, render cards, write caption.

Outputs posts/YYYY-MM-DD-1.jpg (cover), -2.jpg, -3.jpg (stories),
and posts/YYYY-MM-DD.txt (caption), dated in IST.
"""

import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from card import make_cover, make_story_card
from news import fetch_headlines

HEADLINE_COUNT = 6
STORIES_PER_CARD = 3

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
        "Swipe for details ➡️ Follow for daily news highlights! 📰",
        "",
        HASHTAGS,
    ]
    return "\n".join(lines)


def main() -> None:
    now_ist = datetime.now(ZoneInfo("Asia/Kolkata"))
    date_str = now_ist.strftime("%Y-%m-%d")
    date_label = now_ist.strftime("%A, %d %B %Y")

    headlines = fetch_headlines(count=HEADLINE_COUNT)
    if len(headlines) < 3:
        print(f"Only {len(headlines)} headlines fetched; aborting.", file=sys.stderr)
        sys.exit(1)

    posts_dir = Path(__file__).resolve().parent.parent / "posts"
    posts_dir.mkdir(exist_ok=True)

    chunks = [
        headlines[i : i + STORIES_PER_CARD]
        for i in range(0, len(headlines), STORIES_PER_CARD)
    ]
    total_pages = 1 + len(chunks)

    make_cover(headlines, date_label, total_pages, str(posts_dir / f"{date_str}-1.jpg"))
    for page, chunk in enumerate(chunks, start=1):
        make_story_card(
            chunk,
            start_number=page * STORIES_PER_CARD - STORIES_PER_CARD + 1,
            date_label=date_label,
            page=page,
            total_pages=total_pages,
            out_path=str(posts_dir / f"{date_str}-{page + 1}.jpg"),
        )

    (posts_dir / f"{date_str}.txt").write_text(
        build_caption(headlines, date_label), encoding="utf-8"
    )

    print(f"Generated {total_pages} cards with {len(headlines)} headlines:")
    for item in headlines:
        print(f"  - {item['title']} ({item['source']})")


if __name__ == "__main__":
    main()
