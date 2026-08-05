"""Nieuws ophalen via Google News RSS (gratis, geen API-sleutel nodig)."""
from __future__ import annotations

import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timezone

import feedparser


@dataclass
class NewsItem:
    title: str
    link: str
    published: str
    source: str

    def as_line(self) -> str:
        when = self.published or "onbekende datum"
        src = f" ({self.source})" if self.source else ""
        return f"[{when}]{src} {self.title}"


def _parse_time(entry) -> str:
    parsed = getattr(entry, "published_parsed", None)
    if parsed:
        return datetime(*parsed[:6], tzinfo=timezone.utc).strftime("%Y-%m-%d")
    return getattr(entry, "published", "")


def fetch_news(company: str, limit: int = 8, language: str = "en-US", kind: str = "stock") -> list[NewsItem]:
    """Zoek recent nieuws over een bedrijf of crypto-munt.

    We zoeken op de naam + een trefwoord ('stock' voor aandelen, 'crypto' voor
    cryptomunten) zodat we financieel-relevante artikelen krijgen. Google News
    RSS is gratis en vereist geen sleutel.
    """
    query = urllib.parse.quote_plus(f"{company} {kind}")
    gl = language.split("-")[-1] if "-" in language else "US"
    url = (
        f"https://news.google.com/rss/search?q={query}"
        f"&hl={language}&gl={gl}&ceid={gl}:{language.split('-')[0]}"
    )
    feed = feedparser.parse(url)

    items: list[NewsItem] = []
    for entry in feed.entries[:limit]:
        items.append(
            NewsItem(
                title=getattr(entry, "title", "").strip(),
                link=getattr(entry, "link", ""),
                published=_parse_time(entry),
                source=getattr(getattr(entry, "source", None), "title", ""),
            )
        )
    return items
