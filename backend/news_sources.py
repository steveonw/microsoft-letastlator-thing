from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen
from xml.etree import ElementTree

from pydantic import BaseModel, ConfigDict, Field

from models import InformationType, PiiRedactionStatus, Source


GDELT_DOC_API = "https://api.gdeltproject.org/api/v2/doc/doc"
MEDIA_CLOUD_SEARCH_API = "https://search.mediacloud.org/api/search/sample"
GOOGLE_NEWS_RSS_API = "https://news.google.com/rss/search"
MEDIA_CLOUD_US_NATIONAL_COLLECTION = 34412234
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


class NewsProviderAttempt(StrictModel):
    provider: str
    status: str
    detail: str
    source_count: int = Field(default=0, ge=0)
    window_start: date | None = None
    window_end: date | None = None


class NewsDiscovery(StrictModel):
    provider: str = "PolicyTrace multi-source news discovery"
    query: str
    checked_at: datetime
    window_start: date | None = None
    window_end: date | None = None
    sources: list[Source] = Field(default_factory=list)
    provider_attempts: list[NewsProviderAttempt] = Field(default_factory=list)
    limitation: str = (
        "News services are used only to discover factual-reporting source pointers. "
        "Stored text is the supplied headline/title, not an article body, and is not "
        "a verified factual claim. Provider coverage and availability vary; open the "
        "original source before relying on factual content."
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

    return " ".join(quote(token) for token in selected[:3])


def historical_publication_window(
    publication_date: date | None,
) -> tuple[date, date]:
    today = date.today()
    if publication_date is None:
        return today - timedelta(days=365), today
    start = publication_date - timedelta(days=30)
    end = min(today, publication_date + timedelta(days=540))
    return start, max(start, end)


def publication_window(publication_date: date | None) -> tuple[date, date]:
    today = date.today()
    rolling_start = today - timedelta(days=89)

    # GDELT DOC 2.0 is a rolling recent-news index. If the policy itself was
    # published inside that window, include a little context before it;
    # otherwise search the currently available recent-news window rather than
    # asking the provider for dates it no longer indexes.
    if publication_date is not None and publication_date >= rolling_start:
        return max(rolling_start, publication_date - timedelta(days=14)), today
    return rolling_start, today


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


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    text = str(value).strip()
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return _parse_seen_date(value)


def _source_id(prefix: str, url: str) -> str:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    return f"source-{prefix}-{digest}"


def _source_pointer(
    *,
    prefix: str,
    raw_url: str,
    title: str,
    agency: str | None,
    published: date | None,
) -> Source | None:
    raw_url = raw_url.strip()
    title = re.sub(r"\s+", " ", title).strip()
    if not raw_url or not title:
        return None

    parsed = urlparse(raw_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None

    domain = (agency or "").strip() or parsed.netloc
    return Source(
        id=_source_id(prefix, raw_url),
        title=title,
        information_type=InformationType.FACTUAL_REPORTING,
        url=raw_url,
        agency=domain,
        published_at=published,
        raw_text=title,
        pii_redaction_status=PiiRedactionStatus.NOT_APPLICABLE,
    )


def _gdelt_article_source(item: dict[str, Any]) -> Source | None:
    raw_url = str(item.get("url") or "")
    title = str(item.get("title") or "")
    parsed = urlparse(raw_url)
    domain = str(item.get("domain") or parsed.netloc)
    return _source_pointer(
        prefix="gdelt",
        raw_url=raw_url,
        title=title,
        agency=domain,
        published=_parse_seen_date(item.get("seendate")),
    )


def _mediacloud_article_source(item: dict[str, Any]) -> Source | None:
    raw_url = str(item.get("url") or "")
    title = str(item.get("title") or "")
    agency = str(item.get("media_name") or item.get("media_url") or "")
    return _source_pointer(
        prefix="mediacloud",
        raw_url=raw_url,
        title=title,
        agency=agency,
        published=_parse_date(item.get("publish_date")),
    )


def fetch_mediacloud_news(
    *,
    policy_title: str,
    publication_date: date | None,
    api_key: str,
    query: str | None = None,
    max_articles: int = DEFAULT_NEWS_ARTICLES,
    timeout: int = 30,
) -> NewsDiscovery:
    if not api_key.strip():
        raise ValueError("Media Cloud API key is required")
    if max_articles < 1 or max_articles > MAX_NEWS_ARTICLES:
        raise ValueError(
            f"max_articles must be between 1 and {MAX_NEWS_ARTICLES}"
        )

    search_query = (query or "").strip() or default_news_query(policy_title)
    start, end = historical_publication_window(publication_date)
    params: dict[str, Any] = {
        "q": search_query,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "platform": "onlinenews-mediacloud",
        "cs": str(MEDIA_CLOUD_US_NATIONAL_COLLECTION),
        "limit": max_articles,
        "fields": [
            "indexed_date",
            "publish_date",
            "id",
            "language",
            "media_name",
            "media_url",
            "title",
            "url",
        ],
    }
    request = Request(
        f"{MEDIA_CLOUD_SEARCH_API}?{urlencode(params, doseq=True)}",
        headers={
            "Authorization": f"Token {api_key.strip()}",
            "Accept": "application/json",
            "User-Agent": DEFAULT_USER_AGENT,
        },
    )
    with urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))

    raw_articles = payload.get("sample", [])
    if not isinstance(raw_articles, list):
        raise ValueError("Media Cloud response did not contain a story sample")

    sources: list[Source] = []
    seen_urls: set[str] = set()
    for item in raw_articles:
        if not isinstance(item, dict):
            continue
        source = _mediacloud_article_source(item)
        if source is None or str(source.url) in seen_urls:
            continue
        seen_urls.add(str(source.url))
        sources.append(source)
        if len(sources) >= max_articles:
            break

    return NewsDiscovery(
        provider="Media Cloud Online News Archive",
        query=search_query,
        checked_at=datetime.now(timezone.utc),
        window_start=start,
        window_end=end,
        sources=sources,
        limitation=(
            "Media Cloud is used for historical news discovery. PolicyTrace stores "
            "headline/title metadata as a factual-reporting pointer, not article body "
            "text or a verified factual claim."
        ),
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
        "startdatetime": _gdelt_datetime(start),
        "enddatetime": _gdelt_datetime(end),
    }

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
        source = _gdelt_article_source(item)
        if source is None or str(source.url) in seen_urls:
            continue
        seen_urls.add(str(source.url))
        sources.append(source)
        if len(sources) >= max_articles:
            break

    return NewsDiscovery(
        provider="GDELT DOC 2.0",
        query=search_query,
        checked_at=datetime.now(timezone.utc),
        window_start=start,
        window_end=end,
        sources=sources,
        limitation=(
            "GDELT is used here for recent news discovery. Article titles/headlines "
            "and metadata are factual-reporting source pointers, not verified factual "
            "claims. Historical coverage may fall outside the provider's rolling "
            "search window."
        ),
    )


def fetch_google_news_rss(
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

    base_query = (query or "").strip() or default_news_query(policy_title)
    start, end = historical_publication_window(publication_date)
    dated_query = (
        f"{base_query} after:{start.isoformat()} before:{end.isoformat()}"
        if publication_date is not None
        else base_query
    )
    params = {
        "q": dated_query,
        "hl": "en-US",
        "gl": "US",
        "ceid": "US:en",
    }
    request = Request(
        f"{GOOGLE_NEWS_RSS_API}?{urlencode(params)}",
        headers={"User-Agent": DEFAULT_USER_AGENT},
    )
    with urlopen(request, timeout=timeout) as response:
        root = ElementTree.fromstring(response.read())

    sources: list[Source] = []
    seen_urls: set[str] = set()
    for item in root.iter("item"):
        raw_url = (item.findtext("link") or "").strip()
        title = (item.findtext("title") or "").strip()
        publisher = item.find("source")
        agency = (
            publisher.text.strip()
            if publisher is not None and publisher.text
            else ""
        )
        published = None
        published_raw = (item.findtext("pubDate") or "").strip()
        if published_raw:
            try:
                published = parsedate_to_datetime(published_raw).date()
            except (TypeError, ValueError, OverflowError):
                published = None

        source = _source_pointer(
            prefix="google-news",
            raw_url=raw_url,
            title=title,
            agency=agency,
            published=published,
        )
        if source is None or str(source.url) in seen_urls:
            continue
        seen_urls.add(str(source.url))
        sources.append(source)
        if len(sources) >= max_articles:
            break

    return NewsDiscovery(
        provider="Google News RSS",
        query=dated_query,
        checked_at=datetime.now(timezone.utc),
        window_start=start,
        window_end=end,
        sources=sources,
        limitation=(
            "Google News RSS is an undocumented best-effort fallback. PolicyTrace "
            "stores only feed-supplied headline, publisher, date, and link metadata; "
            "it does not treat the headline as a verified factual claim."
        ),
    )


def _attempt_detail(exc: Exception) -> str:
    if isinstance(exc, HTTPError):
        if exc.code == 429:
            return "HTTP 429 rate limited; no retry was attempted."
        if exc.code == 503:
            return "HTTP 503 temporarily unavailable; no retry was attempted."
        return f"HTTP {exc.code}; provider request failed."
    return f"{type(exc).__name__}: {exc}"


def discover_news(
    *,
    policy_title: str,
    publication_date: date | None,
    query: str | None = None,
    max_articles: int = DEFAULT_NEWS_ARTICLES,
    media_cloud_api_key: str = "",
) -> NewsDiscovery:
    if max_articles < 1 or max_articles > MAX_NEWS_ARTICLES:
        raise ValueError(
            f"max_articles must be between 1 and {MAX_NEWS_ARTICLES}"
        )

    search_query = (query or "").strip() or default_news_query(policy_title)
    attempts: list[NewsProviderAttempt] = []
    sources: list[Source] = []
    seen_urls: set[str] = set()
    seen_titles: set[tuple[str, str]] = set()

    def add_from(discovery: NewsDiscovery) -> int:
        added = 0
        for source in discovery.sources:
            url = str(source.url) if source.url else ""
            title_key = (
                source.title.casefold().strip(),
                (source.agency or "").casefold().strip(),
            )
            if url in seen_urls or title_key in seen_titles:
                continue
            if url:
                seen_urls.add(url)
            seen_titles.add(title_key)
            sources.append(source)
            added += 1
            if len(sources) >= max_articles:
                break
        return added

    if media_cloud_api_key.strip():
        start, end = historical_publication_window(publication_date)
        try:
            result = fetch_mediacloud_news(
                policy_title=policy_title,
                publication_date=publication_date,
                api_key=media_cloud_api_key,
                query=search_query,
                max_articles=max_articles,
            )
            added = add_from(result)
            attempts.append(
                NewsProviderAttempt(
                    provider=result.provider,
                    status="used" if added else "empty",
                    detail=(
                        f"Added {added} historical source pointer(s)."
                        if added
                        else "No matching historical stories were returned."
                    ),
                    source_count=added,
                    window_start=start,
                    window_end=end,
                )
            )
        except Exception as exc:
            attempts.append(
                NewsProviderAttempt(
                    provider="Media Cloud Online News Archive",
                    status="failed",
                    detail=_attempt_detail(exc),
                    window_start=start,
                    window_end=end,
                )
            )
    else:
        start, end = historical_publication_window(publication_date)
        attempts.append(
            NewsProviderAttempt(
                provider="Media Cloud Online News Archive",
                status="skipped",
                detail="No Media Cloud API key configured.",
                window_start=start,
                window_end=end,
            )
        )

    if len(sources) < max_articles:
        start, end = publication_window(publication_date)
        try:
            result = fetch_gdelt_news(
                policy_title=policy_title,
                publication_date=publication_date,
                query=search_query,
                max_articles=max_articles - len(sources),
            )
            added = add_from(result)
            attempts.append(
                NewsProviderAttempt(
                    provider=result.provider,
                    status="used" if added else "empty",
                    detail=(
                        f"Added {added} recent source pointer(s)."
                        if added
                        else "No matching recent stories were returned."
                    ),
                    source_count=added,
                    window_start=start,
                    window_end=end,
                )
            )
        except Exception as exc:
            attempts.append(
                NewsProviderAttempt(
                    provider="GDELT DOC 2.0",
                    status="failed",
                    detail=_attempt_detail(exc),
                    window_start=start,
                    window_end=end,
                )
            )

    if len(sources) < max_articles:
        start, end = historical_publication_window(publication_date)
        try:
            result = fetch_google_news_rss(
                policy_title=policy_title,
                publication_date=publication_date,
                query=search_query,
                max_articles=max_articles - len(sources),
            )
            added = add_from(result)
            attempts.append(
                NewsProviderAttempt(
                    provider=result.provider,
                    status="used" if added else "empty",
                    detail=(
                        f"Added {added} fallback source pointer(s)."
                        if added
                        else "No matching RSS stories were returned."
                    ),
                    source_count=added,
                    window_start=start,
                    window_end=end,
                )
            )
        except Exception as exc:
            attempts.append(
                NewsProviderAttempt(
                    provider="Google News RSS",
                    status="failed",
                    detail=_attempt_detail(exc),
                    window_start=start,
                    window_end=end,
                )
            )

    return NewsDiscovery(
        query=search_query,
        checked_at=datetime.now(timezone.utc),
        window_start=None,
        window_end=None,
        sources=sources,
        provider_attempts=attempts,
    )
