"""Fetch top India news headlines from RSS feeds of major outlets."""

import re

import feedparser
import requests

FEEDS = [
    ("Times of India", "https://timesofindia.indiatimes.com/rssfeedstopstories.cms"),
    ("The Hindu", "https://www.thehindu.com/news/national/feeder/default.rss"),
    ("NDTV", "https://feeds.feedburner.com/ndtvnews-top-stories"),
    ("Indian Express", "https://indianexpress.com/section/india/feed/"),
]

MAX_PER_FEED = 3


def _clean(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\s+", " ", text).strip()


def fetch_headlines(count: int = 5) -> list[dict]:
    """Return up to `count` headlines as {"title": ..., "source": ...} dicts.

    Interleaves feeds so no single outlet dominates, and dedupes
    near-identical titles.
    """
    per_feed = []
    for source, url in FEEDS:
        try:
            resp = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
            resp.raise_for_status()
            parsed = feedparser.parse(resp.content)
        except Exception:
            continue
        items = []
        for entry in parsed.entries[:MAX_PER_FEED]:
            title = _clean(entry.get("title", ""))
            if title:
                items.append({"title": title, "source": source})
        per_feed.append(items)

    headlines: list[dict] = []
    seen: set[str] = set()
    for rank in range(MAX_PER_FEED):
        for items in per_feed:
            if rank >= len(items):
                continue
            item = items[rank]
            key = re.sub(r"[^a-z0-9]", "", item["title"].lower())[:60]
            if key in seen:
                continue
            seen.add(key)
            headlines.append(item)
            if len(headlines) >= count:
                return headlines
    return headlines
