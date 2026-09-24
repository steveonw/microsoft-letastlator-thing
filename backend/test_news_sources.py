from __future__ import annotations

import json
import unittest
from datetime import date, timedelta
from unittest.mock import patch

from models import InformationType, PiiRedactionStatus
from news_sources import (
    default_news_query,
    discover_news,
    fetch_gdelt_news,
    historical_publication_window,
    publication_window,
)


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


class NewsSourceTests(unittest.TestCase):
    def test_old_policy_uses_recent_rolling_window(self) -> None:
        start, end = publication_window(date(2023, 10, 23))
        today = date.today()

        self.assertEqual(end, today)
        self.assertEqual(start, today - timedelta(days=89))

    def test_recent_policy_keeps_context_before_publication(self) -> None:
        today = date.today()
        publication = today - timedelta(days=10)

        start, end = publication_window(publication)

        self.assertEqual(end, today)
        self.assertEqual(start, publication - timedelta(days=14))

    def test_default_query_prefers_distinctive_policy_terms(self) -> None:
        query = default_news_query(
            "Modernizing H-1B Requirements, Providing Flexibility in the F-1 Program"
        )

        self.assertIn('"H-1B"', query)
        self.assertIn('"F-1"', query)
        self.assertNotIn(" AND ", query)

    def test_gdelt_results_are_factual_reporting_source_pointers(self) -> None:
        payload = {
            "articles": [
                {
                    "url": "https://example.com/article-one",
                    "title": "Agency issues updated H-1B rule guidance",
                    "domain": "example.com",
                    "seendate": "20260920T120000Z",
                },
                {
                    "url": "https://example.com/article-one",
                    "title": "Duplicate URL should be ignored",
                    "domain": "example.com",
                    "seendate": "20260920T120000Z",
                },
                {
                    "url": "https://news.example.org/article-two",
                    "title": "Employers prepare for H-1B changes",
                    "domain": "news.example.org",
                    "seendate": "20260921T120000Z",
                },
            ]
        }

        with patch(
            "news_sources.urlopen",
            return_value=_FakeResponse(payload),
        ):
            discovery = fetch_gdelt_news(
                policy_title=(
                    "Modernizing H-1B Requirements, Providing Flexibility "
                    "in the F-1 Program"
                ),
                publication_date=date(2023, 10, 23),
                max_articles=8,
            )

        self.assertEqual(len(discovery.sources), 2)
        first = discovery.sources[0]
        self.assertEqual(
            first.information_type,
            InformationType.FACTUAL_REPORTING,
        )
        self.assertEqual(
            first.pii_redaction_status,
            PiiRedactionStatus.NOT_APPLICABLE,
        )
        self.assertEqual(first.raw_text, first.title)
        self.assertEqual(first.agency, "example.com")
        self.assertEqual(first.published_at, date(2026, 9, 20))
        self.assertIn("not verified factual claims", discovery.limitation)
        self.assertIn("rolling", discovery.limitation)

    def test_invalid_article_urls_are_discarded(self) -> None:
        payload = {
            "articles": [
                {
                    "url": "javascript:alert(1)",
                    "title": "Bad source",
                },
                {
                    "url": "https://valid.example/story",
                    "title": "Valid source",
                    "seendate": "20260922T000000Z",
                },
            ]
        }

        with patch(
            "news_sources.urlopen",
            return_value=_FakeResponse(payload),
        ):
            discovery = fetch_gdelt_news(
                policy_title="H-1B Modernization Rule",
                publication_date=date(2023, 10, 23),
                max_articles=8,
            )

        self.assertEqual(len(discovery.sources), 1)
        self.assertEqual(
            str(discovery.sources[0].url),
            "https://valid.example/story",
        )

    def test_historical_window_surrounds_old_policy(self) -> None:
        start, end = historical_publication_window(date(2023, 10, 23))

        self.assertEqual(start, date(2023, 9, 23))
        self.assertEqual(end, date(2025, 4, 15))

    def test_provider_chain_survives_gdelt_failure_and_uses_rss(self) -> None:
        rss = b"""<?xml version="1.0" encoding="UTF-8"?>
        <rss><channel>
          <item>
            <title>Archived coverage of H-1B modernization</title>
            <link>https://news.example/story</link>
            <pubDate>Mon, 18 Dec 2023 12:00:00 GMT</pubDate>
            <source>Example News</source>
          </item>
        </channel></rss>"""

        class _BytesResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self) -> bytes:
                return rss

        def fake_urlopen(request, timeout=30):
            del timeout
            url = request.full_url
            if "api.gdeltproject.org" in url:
                raise RuntimeError("rate limited")
            if "news.google.com" in url:
                return _BytesResponse()
            raise AssertionError(url)

        with patch("news_sources.urlopen", side_effect=fake_urlopen):
            result = discover_news(
                policy_title="H-1B Modernization Rule",
                publication_date=date(2023, 10, 23),
                max_articles=8,
            )

        self.assertEqual(len(result.sources), 1)
        self.assertEqual(result.sources[0].title, "Archived coverage of H-1B modernization")
        self.assertEqual(
            [attempt.status for attempt in result.provider_attempts],
            ["skipped", "failed", "used"],
        )
        self.assertIsNone(result.window_start)
        self.assertIsNone(result.window_end)
        self.assertEqual(
            result.provider_attempts[0].window_start,
            date(2023, 9, 23),
        )
        self.assertEqual(
            result.provider_attempts[1].window_end,
            date.today(),
        )


if __name__ == "__main__":
    unittest.main()
