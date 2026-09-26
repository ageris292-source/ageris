"""Google News RSS search provider (headlines only; unofficial, UNLICENSED).

Only the headline, publisher, link and publication time are used — article
bodies are never scraped (spec §78: agents must not scrape random websites).
An item without a parseable publication time is kept for display but marked
`historical_use = false` (spec §34).
"""

from __future__ import annotations

import calendar
import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime

import feedparser
import httpx

from app.market_data.providers.base import ProviderError, ProviderUnavailableError

URL = "https://news.google.com/rss/search"


@dataclass(frozen=True)
class RawNews:
    title: str
    publisher: str | None
    url: str
    published_at: datetime | None

    @property
    def title_key(self) -> str:
        """Normalised headline hash for exact-duplicate detection."""
        t = re.sub(r"[^a-z0-9 ]+", " ", self.title.lower())
        return hashlib.sha256(" ".join(t.split()).encode()).hexdigest()[:32]


def _clean_title(title: str, publisher: str | None) -> str:
    # Google appends " - Publisher" to every headline.
    if publisher and title.endswith(f" - {publisher}"):
        return title[: -len(publisher) - 3].strip()
    return title.strip()


def parse_rss(xml: str, limit: int) -> list[RawNews]:
    feed = feedparser.parse(xml)
    if feed.bozo and not feed.entries:
        raise ProviderError("news feed is not valid RSS")
    out: list[RawNews] = []
    for e in feed.entries[:limit]:
        publisher = (e.get("source") or {}).get("title")
        title = _clean_title(e.get("title", ""), publisher)
        link = e.get("link")
        if not title or not link:
            continue
        parsed = e.get("published_parsed")
        published = datetime.fromtimestamp(calendar.timegm(parsed), UTC) if parsed else None
        out.append(RawNews(title, publisher, link, published))
    return out


class GoogleNewsProvider:
    name = "google_news_rss"
    licensed = False

    def __init__(self, enabled: bool, limit: int, transport: httpx.BaseTransport | None = None):
        self.enabled, self.limit, self._transport = enabled, limit, transport

    def fetch(self, query: str) -> tuple[list[RawNews], datetime]:
        if not self.enabled:
            raise ProviderUnavailableError("news provider disabled in configuration")
        params = {"q": query, "hl": "en-IN", "gl": "IN", "ceid": "IN:en"}
        try:
            with httpx.Client(
                transport=self._transport,
                timeout=15,
                headers={"User-Agent": "Mozilla/5.0 (Aegis research)"},
            ) as c:
                resp = c.get(URL, params=params)
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError(f"news unreachable: {exc.__class__.__name__}") from exc
        if resp.status_code != 200:
            raise ProviderUnavailableError(f"news provider returned HTTP {resp.status_code}")
        return parse_rss(resp.text, self.limit), datetime.now(UTC)


def query_for(symbol: str, name: str | None) -> str:
    """Search by company name when known (symbols like 'TCS' are ambiguous)."""
    if name:
        short = re.sub(r"\b(Limited|Ltd\.?)\b", "", name).strip()
        return f'"{short}" OR "{symbol} share"'
    return f'"{symbol} share" OR "{symbol} stock"'
