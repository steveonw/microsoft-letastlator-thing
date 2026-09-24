from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from pydantic import BaseModel, ConfigDict, Field

from models import InformationType, PiiRedactionStatus, Source


GDELT_DOC_API = "https://api.gdeltproject.org/api/v2/doc/doc"
DEFAULT_USER_AGENT = (
    "PolicyTrace/0.1 (+https://github.com/steveonw/microsoft-letastlator-thing)"
)
MAX_NEWS_ARTICLES = 25
DEFAULT_NEWS_ARTICLES = 8

_STOPWORDS = {
    "a", "an", "and", "as", "at", "by", "for", "from", "in", "into",
    "of", "on", "or", "other", "providing", "requirements", "the", "to",
    "under", "with",
}
_TOKEN_RE = re.compile(r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*")


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NewsDiscovery(StrictModel):
    provider: str = "GDELT DOC 2.0"
    query: str
    checked_at: datetime
    window_start: date | None = None
    window_end: date | None = None
    sources: list[Source] = Field(default_factory=list)
    limitation: str = (
        "GDELT is used here for news discovery. Article titles/headlines and "
        "metadata are factual-reporting source pointers, not verified factual "
        "claims. Open the original article before relying on its factual content."
    )


def default_news_query(title: str) -> str:
    tokens = []
    seen: set[str] = set()
    for match in _TOKEN_RE.finditer(title):
        token = match.group(0)
        key = token.casefold()
        if key in _STOPWORDS or key in seen or len(token) < 2:
            continue
        seen.add(key)
        tokens.append(token)

    if not tokens:
        raise ValueError("Could not derive a news query from the policy title")

    distinctive = [
        token
        for token in tokens
        if any(char.isdigit() for char in token) or "-" in token
    ]
    selected = distinctive[:2]
    if len(selected) < 2:
        remaining = [
            token
            for token in sorted(tokens, key=lambda item: (-len(item), item.casefold()))
            if token not in selected
        ]
        selected.extend(remaining[: 3 - len(selected)])

    def quote(token: str) -> str:
        escaped = token.replace('"', "")
        return f'"{escaped}"' if "-" in escaped or " " in escaped else escaped

    return " AND ".join(quote(token) for token in selected[:3])


def publication_window(publication_date: date | None) -> tuple[date | None, date | None]:
    if publication_date is None:
        return None, None
    start = publication_date - timedelta(days=30)
    end = min(date.today(), publication_date + timedelta(days=540))
    if end < start:
        end = date.today()
    return start, end


def _gdelt_datetime(value: date) -> str:
    return value.strftime("%Y%m%d000000")


def _parse_seen_date(value: Any) -> date | None:
    if not value:
        return None
    text = str(value).strip()
    for fmt in ("%Y%m%dT%H%M%SZ", "%Y%m%d%H%M%S", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _source_id(url: str) -> str:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    return f"source-gdelt-{digest}"


def _article_source(item: dict[str, Any]) -> Source | None:
    raw_url = str(item.get("url") or "").strip()
    title = re.sub(r"\s+", " ", str(item.get("title") or "")).strip()
    if not raw_url or not title:
        return None

    parsed = urlparse(raw_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None

    domain = str(item.get("domain") or parsed.netloc).strip() or parsed.netloc
    published = _parse_seen_date(item.get("seendate"))
    return Source(
        id=_source_id(raw_url),
        title=title,
        information_type=InformationType.FACTUAL_REPORTING,
        url=raw_url,
        agency=domain,
        published_at=published,
        raw_text=title,
        pii_redaction_status=PiiRedactionStatus.NOT_APPLICABLE,
    )


def fetch_gdelt_news(
    *,
    policy_title: str,
    publication_date: date | None,
    query: str | None = None,
    max_articles: int = DEFAULT_NEWS_ARTICLES,
    timeout: int = 30,
) -> NewsDiscovery:
    if max_articles < 1 or max_articles > MAX_NEWS_ARTICLES:
        raise ValueError(
            f"max_articles must be between 1 and {MAX_NEWS_ARTICLES}"
        )

    search_query = (query or "").strip() or default_news_query(policy_title)
    start, end = publication_window(publication_date)
    params: dict[str, Any] = {
        "query": search_query,
        "mode": "artlist",
        "format": "json",
        "sort": "datedesc",
        # GDELT commonly returns larger article-list pages; request a modest
        # page and slice locally to the user's requested count.
        "maxrecords": max(25, max_articles),
    }
    if start is not None:
        params["startdatetime"] = _gdelt_datetime(start)
    if end is not None:
        params["enddatetime"] = _gdelt_datetime(end)

    request = Request(
        f"{GDELT_DOC_API}?{urlencode(params)}",
        headers={
            "Accept": "application/json",
            "User-Agent": DEFAULT_USER_AGENT,
        },
    )
    with urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))

    raw_articles = payload.get("articles", [])
    if not isinstance(raw_articles, list):
        raise ValueError("GDELT response did not contain an article list")

    sources: list[Source] = []
    seen_urls: set[str] = set()
    for item in raw_articles:
        if not isinstance(item, dict):
            continue
        source = _article_source(item)
        if source is None or str(source.url) in seen_urls:
            continue
        seen_urls.add(str(source.url))
        sources.append(source)
        if len(sources) >= max_articles:
            break

    return NewsDiscovery(
        query=search_query,
        checked_at=datetime.now(timezone.utc),
        window_start=start,
        window_end=end,
        sources=sources,
    )
