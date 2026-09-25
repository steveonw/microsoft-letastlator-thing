import unittest
import warnings
from datetime import date, datetime, timezone
from unittest.mock import patch

from federal_register import NormalizedChunk, NormalizedPolicyDocument
from models import InformationType, PiiRedactionStatus, StepKind, VerificationStatus
from response_sources import (
    CommentFetchError,
    ResponseRecord,
    _attachment_candidates,
    _combine_comment_and_attachments,
    _comment_record_from_detail,
    _download_attachment_bytes,
    _extract_attachment_payload,
    fetch_comments_for_docket,
    fetch_comments_for_docket_with_report,
    extraction_is_degraded,
    _validate_attachment_url,
    duplicate_cluster_id,
    is_attachment_placeholder,
    sanitize_public_text,
    source_from_response_record,
)
from response_viewpoint_analyst import (
    ResponseEvidenceRef,
    ResponseViewpointOutput,
    ViewpointFinding,
    build_response_analysis,
    build_response_viewpoint_prompt,
)


POLICY_TEXT = "SUPPLEMENTARY INFORMATION:\nSynthetic policy text for Chunk 5 tests."


def policy_document() -> NormalizedPolicyDocument:
    return NormalizedPolicyDocument(
        document_number="demo-5",
        title="Synthetic proposed rule",
        document_type="Proposed Rule",
        action="Proposed rule; request for comment",
        agency_names=["Demo Agency"],
        publication_date=date(2026, 1, 2),
        citation="99 FR 500",
        html_url="https://example.gov/policy",
        raw_text=POLICY_TEXT,
        chunks=[
            NormalizedChunk(
                id="demo-5-chunk-001",
                sequence=1,
                heading="SUPPLEMENTARY INFORMATION",
                text=POLICY_TEXT,
                start_offset=0,
                end_offset=len(POLICY_TEXT),
            )
        ],
    )


def public_source(record_id: str, text: str):
    return source_from_response_record(
        ResponseRecord(
            id=record_id,
            title=f"Comment {record_id}",
            text=text,
            information_type=InformationType.PUBLIC_OPINION,
            url=f"https://example.invalid/{record_id}",
            posted_at=datetime(2026, 1, 3, tzinfo=timezone.utc),
        )
    )


class ResponseSourceTests(unittest.TestCase):
    def test_sanitize_public_text_redacts_email_and_phone(self) -> None:
        clean, status = sanitize_public_text(
            "Contact person@example.com or 202-555-0182."
        )

        self.assertEqual(status, PiiRedactionStatus.REDACTED)
        self.assertNotIn("person@example.com", clean)
        self.assertNotIn("202-555-0182", clean)
        self.assertIn("[REDACTED EMAIL]", clean)
        self.assertIn("[REDACTED PHONE]", clean)

    def test_duplicate_cluster_normalizes_case_and_spacing(self) -> None:
        self.assertEqual(
            duplicate_cluster_id("Same   comment\ntext"),
            duplicate_cluster_id("same comment text"),
        )

    def test_regulations_detail_parser_ignores_identity_fields(self) -> None:
        record = _comment_record_from_detail(
            "DEMO-0001",
            {
                "data": {
                    "attributes": {
                        "title": "Public comment",
                        "comment": "Please clarify the implementation threshold.",
                        "postedDate": "2026-01-03T10:00:00Z",
                        "organization": "Example Org",
                        "firstName": "Should",
                        "lastName": "NotImport",
                    }
                }
            },
        )

        self.assertIsNotNone(record)
        self.assertEqual(record.id, "DEMO-0001")
        self.assertEqual(record.organization, "Example Org")
        self.assertFalse(hasattr(record, "firstName"))
        self.assertFalse(hasattr(record, "lastName"))

    def test_attachment_candidates_prefer_text_then_pdf(self) -> None:
        detail = {
            "included": [
                {
                    "type": "attachments",
                    "attributes": {
                        "title": "Comment letter",
                        "fileFormats": [
                            {
                                "fileUrl": "https://downloads.regulations.gov/DEMO/attachment_1.pdf",
                                "format": "pdf",
                                "size": 1000,
                            },
                            {
                                "fileUrl": "https://downloads.regulations.gov/DEMO/attachment_1.txt",
                                "format": "txt",
                                "size": 500,
                            },
                        ],
                    },
                }
            ]
        }

        attachments = _attachment_candidates(detail)

        self.assertEqual(len(attachments), 1)
        title, formats = attachments[0]
        self.assertEqual(title, "Comment letter")
        self.assertEqual(formats[0]["format"], "txt")
        self.assertEqual(formats[1]["format"], "pdf")

    def test_attachment_placeholder_is_replaced_by_extracted_text(self) -> None:
        combined = _combine_comment_and_attachments(
            "See attached file(s)",
            [("Comment letter", "Substantive attachment text.")],
        )

        self.assertNotIn("See attached file", combined)
        self.assertIn("Attachment: Comment letter", combined)
        self.assertIn("Substantive attachment text.", combined)

    def test_inline_comment_and_attachment_are_both_preserved(self) -> None:
        combined = _combine_comment_and_attachments(
            "Please see the attached analysis.",
            [("Analysis", "Detailed supporting text.")],
        )

        self.assertTrue(combined.startswith("Please see the attached analysis."))
        self.assertIn("Attachment: Analysis", combined)
        self.assertIn("Detailed supporting text.", combined)

    def test_html_attachment_extraction_decodes_entities(self) -> None:
        text = _extract_attachment_payload(
            b"<p>Transparency &amp; accountability</p><p>Second point.</p>",
            "html",
        )

        self.assertIn("Transparency & accountability", text)
        self.assertIn("Second point.", text)

    def test_attachment_download_uses_browser_style_headers(self) -> None:
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self, size):
                self.size = size
                return b"attachment bytes"

        captured = {}

        def fake_urlopen(request, timeout):
            captured["headers"] = dict(request.header_items())
            captured["timeout"] = timeout
            return FakeResponse()

        with patch("response_sources.urlopen", side_effect=fake_urlopen):
            payload = _download_attachment_bytes(
                "https://downloads.regulations.gov/DEMO/attachment_1.pdf",
                timeout=17,
            )

        self.assertEqual(payload, b"attachment bytes")
        self.assertEqual(captured["timeout"], 17)
        self.assertIn("Mozilla/5.0", captured["headers"]["User-agent"])
        self.assertEqual(
            captured["headers"]["Referer"],
            "https://www.regulations.gov/",
        )

    def test_attachment_download_host_is_restricted(self) -> None:
        _validate_attachment_url(
            "https://downloads.regulations.gov/DEMO/attachment_1.pdf"
        )

        with self.assertRaises(ValueError):
            _validate_attachment_url("https://example.com/attachment.pdf")

    def test_comment_record_can_use_attachment_only_text(self) -> None:
        record = _comment_record_from_detail(
            "DEMO-ATTACHMENT",
            {
                "data": {
                    "attributes": {
                        "title": "Attachment-only comment",
                        "comment": "See attached file(s).",
                        "postedDate": "2026-01-03T10:00:00Z",
                    }
                }
            },
            attachment_texts=[
                ("Submitted letter", "The attachment contains the actual comment.")
            ],
        )

        self.assertIsNotNone(record)
        self.assertNotIn("See attached file", record.text)
        self.assertIn("The attachment contains the actual comment.", record.text)

    def test_attachment_placeholder_has_no_duplicate_cluster(self) -> None:
        source = public_source("placeholder", "See attached file(s)")

        self.assertTrue(is_attachment_placeholder(source.raw_text))
        self.assertIsNone(source.duplicate_cluster_id)

    def test_source_keeps_response_type_and_duplicate_cluster(self) -> None:
        source = public_source("a", "A response statement.")

        self.assertEqual(source.information_type, InformationType.PUBLIC_OPINION)
        self.assertTrue(source.duplicate_cluster_id)
        self.assertEqual(
            source.pii_redaction_status,
            PiiRedactionStatus.NOT_DETECTED,
        )

    def test_live_comments_use_bounded_parallel_detail_fetches_in_stable_order(self) -> None:
        calls: list[tuple[str, int]] = []
        captured: dict[str, object] = {}

        class FakeFuture:
            def __init__(self, value=None, error=None):
                self.value = value
                self.error = error

            def result(self):
                if self.error is not None:
                    raise self.error
                return self.value

        class FakeExecutor:
            def __init__(self, max_workers: int):
                captured["max_workers"] = max_workers

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def submit(self, fn, comment_id, **kwargs):
                captured.setdefault("ids", []).append(comment_id)
                try:
                    return FakeFuture(fn(comment_id, **kwargs))
                except Exception as exc:
                    return FakeFuture(error=exc)

        def fake_get_json(path, *, api_key, params=None, timeout=30):
            del api_key, params
            calls.append((path, timeout))
            if path == "/documents":
                return {
                    "data": [
                        {"attributes": {"objectId": "OBJ-1"}},
                    ]
                }
            if path == "/comments":
                return {
                    "data": [
                        {"id": "COMMENT-1"},
                        {"id": "COMMENT-2"},
                        {"id": "COMMENT-3"},
                    ]
                }
            comment_id = path.rsplit("/", 1)[-1]
            return {
                "data": {
                    "attributes": {
                        "title": comment_id,
                        "comment": f"Text for {comment_id}.",
                        "postedDate": "2026-01-03T10:00:00Z",
                    }
                }
            }

        with (
            patch("response_sources._get_json", side_effect=fake_get_json),
            patch("response_sources._extract_attachment_texts", return_value=[]),
            patch("response_sources.ThreadPoolExecutor", FakeExecutor),
        ):
            records = fetch_comments_for_docket(
                "DEMO-DOCKET",
                api_key="test-key",
                max_comments=3,
                timeout=11,
            )

        self.assertEqual(
            [record.id for record in records],
            ["COMMENT-1", "COMMENT-2", "COMMENT-3"],
        )
        self.assertEqual(captured["max_workers"], 3)
        self.assertEqual(
            captured["ids"],
            ["COMMENT-1", "COMMENT-2", "COMMENT-3"],
        )
        self.assertIn(("/comments/COMMENT-1", 11), calls)

    def test_live_comments_replace_failed_detail_fetches_when_more_are_available(self) -> None:
        def fake_get_json(path, *, api_key, params=None, timeout=30):
            del api_key, params, timeout
            if path == "/documents":
                return {"data": [{"attributes": {"objectId": "OBJ-1"}}]}
            if path == "/comments":
                return {
                    "data": [
                        {"id": "COMMENT-1"},
                        {"id": "COMMENT-2"},
                        {"id": "COMMENT-3"},
                        {"id": "COMMENT-4"},
                    ]
                }
            raise AssertionError(f"unexpected path {path}")

        def fake_fetch(comment_id, *, api_key, timeout):
            del api_key, timeout
            if comment_id == "COMMENT-2":
                raise RuntimeError("rate limited")
            return ResponseRecord(
                id=comment_id,
                title=comment_id,
                text=f"Text for {comment_id}.",
                information_type=InformationType.PUBLIC_OPINION,
            )

        with (
            patch("response_sources._get_json", side_effect=fake_get_json),
            patch("response_sources._fetch_comment_record", side_effect=fake_fetch),
        ):
            result = fetch_comments_for_docket_with_report(
                "DEMO-DOCKET",
                api_key="test-key",
                max_comments=3,
            )

        self.assertEqual(
            [record.id for record in result.records],
            ["COMMENT-1", "COMMENT-3", "COMMENT-4"],
        )
        self.assertEqual(result.report.requested_count, 3)
        self.assertEqual(result.report.retrieved_count, 3)
        self.assertEqual(result.report.attempted_count, 4)
        self.assertEqual(len(result.report.failures), 1)
        self.assertEqual(result.report.failures[0].comment_id, "COMMENT-2")
        self.assertEqual(result.report.failures[0].error_type, "RuntimeError")

    def test_live_comments_report_partial_gap_when_replacement_is_unavailable(self) -> None:
        def fake_get_json(path, *, api_key, params=None, timeout=30):
            del api_key, params, timeout
            if path == "/documents":
                return {"data": [{"attributes": {"objectId": "OBJ-1"}}]}
            if path == "/comments":
                return {
                    "data": [
                        {"id": "COMMENT-1"},
                        {"id": "COMMENT-2"},
                    ]
                }
            raise AssertionError(f"unexpected path {path}")

        def fake_fetch(comment_id, *, api_key, timeout):
            del api_key, timeout
            if comment_id == "COMMENT-2":
                raise TimeoutError("request timed out")
            return ResponseRecord(
                id=comment_id,
                title=comment_id,
                text=f"Text for {comment_id}.",
                information_type=InformationType.PUBLIC_OPINION,
            )

        with (
            patch("response_sources._get_json", side_effect=fake_get_json),
            patch("response_sources._fetch_comment_record", side_effect=fake_fetch),
        ):
            result = fetch_comments_for_docket_with_report(
                "DEMO-DOCKET",
                api_key="test-key",
                max_comments=2,
            )

        self.assertEqual([record.id for record in result.records], ["COMMENT-1"])
        self.assertEqual(result.report.retrieved_count, 1)
        self.assertEqual(result.report.attempted_count, 2)
        self.assertEqual(result.report.failures[0].error_type, "TimeoutError")

    def test_live_comments_raise_when_every_attempt_fails(self) -> None:
        def fake_get_json(path, *, api_key, params=None, timeout=30):
            del api_key, params, timeout
            if path == "/documents":
                return {"data": [{"attributes": {"objectId": "OBJ-1"}}]}
            if path == "/comments":
                return {
                    "data": [
                        {"id": "COMMENT-1"},
                        {"id": "COMMENT-2"},
                    ]
                }
            raise AssertionError(f"unexpected path {path}")

        with (
            patch("response_sources._get_json", side_effect=fake_get_json),
            patch(
                "response_sources._fetch_comment_record",
                side_effect=RuntimeError("provider unavailable"),
            ),
        ):
            with self.assertRaises(CommentFetchError) as raised:
                fetch_comments_for_docket_with_report(
                    "DEMO-DOCKET",
                    api_key="test-key",
                    max_comments=2,
                )

        report = raised.exception.report
        self.assertEqual(report.retrieved_count, 0)
        self.assertEqual(report.attempted_count, 2)
        self.assertEqual(len(report.failures), 2)

    def test_random_comment_sampling_is_reproducible_across_document_objects(self) -> None:
        def fake_get_json(path, *, api_key, params=None, timeout=30):
            del api_key, timeout
            params = params or {}
            if path == "/documents":
                return {
                    "data": [
                        {"attributes": {"objectId": "OBJ-B"}},
                        {"attributes": {"objectId": "OBJ-A"}},
                    ]
                }
            if path == "/comments":
                object_id = params["filter[commentOnId]"]
                if params.get("page[size]") == 5:
                    return {
                        "data": [{"id": f"{object_id}-COUNT"}],
                        "meta": {
                            "totalElements": 5 if object_id == "OBJ-A" else 7
                        },
                    }
                count = 5 if object_id == "OBJ-A" else 7
                return {
                    "data": [
                        {"id": f"{object_id}-COMMENT-{index}"}
                        for index in range(1, count + 1)
                    ],
                    "meta": {"totalElements": count},
                }
            raise AssertionError(f"unexpected path {path}")

        def fake_fetch(comment_id, *, api_key, timeout):
            del api_key, timeout
            return ResponseRecord(
                id=comment_id,
                title=comment_id,
                text=f"Text for {comment_id}.",
                information_type=InformationType.PUBLIC_OPINION,
            )

        def run(seed):
            with (
                patch("response_sources._get_json", side_effect=fake_get_json),
                patch(
                    "response_sources._fetch_comment_record",
                    side_effect=fake_fetch,
                ),
            ):
                return fetch_comments_for_docket_with_report(
                    "DEMO-DOCKET",
                    api_key="test-key",
                    max_comments=4,
                    sampling_method="random",
                    sampling_seed=seed,
                )

        first = run(48213)
        second = run(48213)

        self.assertEqual(first.report.population_count, 12)
        self.assertEqual(first.report.population_object_ids, ["OBJ-A", "OBJ-B"])
        self.assertEqual(first.report.selected_positions, second.report.selected_positions)
        self.assertEqual(
            first.report.selected_comment_ids,
            second.report.selected_comment_ids,
        )
        self.assertEqual(
            len(first.report.selected_positions),
            len(set(first.report.selected_positions)),
        )
        self.assertEqual(first.report.sampling_seed, 48213)
        self.assertTrue(first.report.page_requests)

    def test_all_regulations_gov_requests_use_valid_page_sizes(self) -> None:
        # Regulations.gov v4 rejects page[size] outside 5..250 with HTTP 400.
        # Offline fakes accept anything, so enforce the live limit here.
        requested_sizes: list[int] = []

        def strict_get_json(path, *, api_key, params=None, timeout=30):
            del api_key, timeout
            params = params or {}
            size = params.get("page[size]")
            if size is not None:
                requested_sizes.append(size)
                if not 5 <= size <= 250:
                    raise AssertionError(
                        f"{path} page[size]={size}; Regulations.gov requires 5..250"
                    )
            if path == "/documents":
                return {"data": [{"attributes": {"objectId": "OBJ-A"}}]}
            if path == "/comments":
                return {
                    "data": [{"id": f"OBJ-A-COMMENT-{i}"} for i in range(1, 9)],
                    "meta": {"totalElements": 8},
                }
            raise AssertionError(f"unexpected path {path}")

        def fake_fetch(comment_id, *, api_key, timeout):
            del api_key, timeout
            return ResponseRecord(
                id=comment_id,
                title=comment_id,
                text=f"Text for {comment_id}.",
                information_type=InformationType.PUBLIC_OPINION,
            )

        for method in ("earliest", "random"):
            with (
                patch("response_sources._get_json", side_effect=strict_get_json),
                patch("response_sources._fetch_comment_record", side_effect=fake_fetch),
            ):
                fetch_comments_for_docket_with_report(
                    "DEMO-DOCKET",
                    api_key="test-key",
                    max_comments=3,
                    sampling_method=method,
                    sampling_seed=7,
                )
        self.assertTrue(requested_sizes)

    def test_random_comment_sampling_changes_with_seed(self) -> None:
        def fake_get_json(path, *, api_key, params=None, timeout=30):
            del api_key, timeout
            params = params or {}
            if path == "/documents":
                return {"data": [{"attributes": {"objectId": "OBJ-1"}}]}
            if path == "/comments" and params.get("page[size]") == 5:
                return {
                    "data": [{"id": "COUNT"}],
                    "meta": {"totalElements": 30},
                }
            if path == "/comments":
                return {
                    "data": [
                        {"id": f"COMMENT-{index}"}
                        for index in range(1, 31)
                    ],
                    "meta": {"totalElements": 30},
                }
            raise AssertionError(f"unexpected path {path}")

        def fake_fetch(comment_id, *, api_key, timeout):
            del api_key, timeout
            return ResponseRecord(
                id=comment_id,
                title=comment_id,
                text=f"Text for {comment_id}.",
                information_type=InformationType.PUBLIC_OPINION,
            )

        def positions(seed):
            with (
                patch("response_sources._get_json", side_effect=fake_get_json),
                patch(
                    "response_sources._fetch_comment_record",
                    side_effect=fake_fetch,
                ),
            ):
                result = fetch_comments_for_docket_with_report(
                    "DEMO-DOCKET",
                    api_key="test-key",
                    max_comments=6,
                    sampling_method="random",
                    sampling_seed=seed,
                )
            return result.report.selected_positions

        self.assertNotEqual(positions(1), positions(2))

    def test_random_sampling_replacements_are_deterministic(self) -> None:
        def fake_get_json(path, *, api_key, params=None, timeout=30):
            del api_key, timeout
            params = params or {}
            if path == "/documents":
                return {"data": [{"attributes": {"objectId": "OBJ-1"}}]}
            if path == "/comments" and params.get("page[size]") == 5:
                return {
                    "data": [{"id": "COUNT"}],
                    "meta": {"totalElements": 20},
                }
            if path == "/comments":
                return {
                    "data": [
                        {"id": f"COMMENT-{index}"}
                        for index in range(1, 21)
                    ],
                    "meta": {"totalElements": 20},
                }
            raise AssertionError(f"unexpected path {path}")

        def successful_fetch(comment_id, *, api_key, timeout):
            del api_key, timeout
            return ResponseRecord(
                id=comment_id,
                title=comment_id,
                text=f"Text for {comment_id}.",
                information_type=InformationType.PUBLIC_OPINION,
            )

        with (
            patch("response_sources._get_json", side_effect=fake_get_json),
            patch(
                "response_sources._fetch_comment_record",
                side_effect=successful_fetch,
            ),
        ):
            baseline = fetch_comments_for_docket_with_report(
                "DEMO-DOCKET",
                api_key="test-key",
                max_comments=4,
                sampling_method="random",
                sampling_seed=99,
            )
        failed_id = baseline.report.selected_comment_ids[0]

        def flaky_fetch(comment_id, *, api_key, timeout):
            if comment_id == failed_id:
                raise RuntimeError("simulated detail failure")
            return successful_fetch(
                comment_id,
                api_key=api_key,
                timeout=timeout,
            )

        def run_with_failure():
            with (
                patch("response_sources._get_json", side_effect=fake_get_json),
                patch(
                    "response_sources._fetch_comment_record",
                    side_effect=flaky_fetch,
                ),
            ):
                return fetch_comments_for_docket_with_report(
                    "DEMO-DOCKET",
                    api_key="test-key",
                    max_comments=4,
                    sampling_method="random",
                    sampling_seed=99,
                )

        first = run_with_failure()
        second = run_with_failure()

        self.assertEqual(first.report.replacement_positions, second.report.replacement_positions)
        self.assertEqual(first.report.selected_comment_ids, second.report.selected_comment_ids)
        self.assertTrue(first.report.replacement_positions)
        self.assertNotIn(failed_id, first.report.selected_comment_ids)
        self.assertEqual(len(first.records), 4)

    def test_random_sampling_rejects_population_beyond_direct_page_limit(self) -> None:
        def fake_get_json(path, *, api_key, params=None, timeout=30):
            del api_key, timeout
            params = params or {}
            if path == "/documents":
                return {"data": [{"attributes": {"objectId": "OBJ-1"}}]}
            if path == "/comments":
                return {
                    "data": [{"id": "COUNT"}],
                    "meta": {"totalElements": 5001},
                }
            raise AssertionError(f"unexpected path {path}")

        with patch("response_sources._get_json", side_effect=fake_get_json):
            with self.assertRaisesRegex(ValueError, "up to 5000"):
                fetch_comments_for_docket_with_report(
                    "DEMO-DOCKET",
                    api_key="test-key",
                    max_comments=12,
                    sampling_method="random",
                    sampling_seed=7,
                )


class ResponseAnalystTests(unittest.TestCase):
    def test_prompt_contains_only_response_material(self) -> None:
        source = public_source("a", "A supplied response statement.")

        prompt = build_response_viewpoint_prompt([source])

        self.assertIn("response-a", prompt)
        self.assertIn("type=public_opinion", prompt)
        self.assertIn("A supplied response statement.", prompt)
        self.assertNotIn(POLICY_TEXT, prompt)

    def test_prompt_excludes_unretrieved_attachment_placeholder(self) -> None:
        placeholder = public_source("placeholder", "See attached file(s)")
        substantive = public_source("real", "Substantive supplied response.")

        prompt = build_response_viewpoint_prompt([placeholder, substantive])

        self.assertNotIn("response-placeholder", prompt)
        self.assertNotIn("See attached file(s)", prompt)
        self.assertIn("response-real", prompt)
        self.assertIn("Substantive supplied response.", prompt)

    def test_findings_become_evidence_linked_draft_claims(self) -> None:
        source_a = public_source(
            "a",
            "I support predictable reporting deadlines.",
        )
        source_b = public_source(
            "b",
            "Please clarify how borderline cases should be handled.",
        )
        output = ResponseViewpointOutput(
            reasons_for_support=[
                ViewpointFinding(
                    text="One supplied comment supports predictable deadlines.",
                    source_type="public_opinion",
                    evidence=[
                        ResponseEvidenceRef(
                            source_id=source_a.id,
                            quote="I support predictable reporting deadlines.",
                        )
                    ],
                    confidence="high",
                )
            ],
            questions_misunderstandings=[
                ViewpointFinding(
                    text="One supplied comment asks for clarification about borderline cases.",
                    source_type="public_opinion",
                    evidence=[
                        ResponseEvidenceRef(
                            source_id=source_b.id,
                            quote="Please clarify how borderline cases should be handled.",
                        )
                    ],
                    confidence="high",
                )
            ],
        )

        analysis = build_response_analysis(
            policy_document(),
            [source_a, source_b],
            output,
        )

        self.assertEqual(len(analysis.steps), 2)
        self.assertEqual(analysis.steps[0].kind, StepKind.PUBLIC_RESPONSE)
        self.assertEqual(analysis.steps[1].kind, StepKind.THEMES_VIEWPOINTS)
        self.assertTrue(analysis.evidence)
        self.assertIn("not a representative sample", analysis.steps[0].ai_output)

        for step in analysis.steps:
            for claim in step.claims:
                self.assertEqual(
                    claim.verification_status,
                    VerificationStatus.NEEDS_HUMAN_REVIEW,
                )
                self.assertTrue(claim.evidence_ids)

        for evidence in analysis.evidence:
            source = next(
                item for item in analysis.sources if item.id == evidence.source_id
            )
            self.assertEqual(
                source.raw_text[evidence.start_offset:evidence.end_offset],
                evidence.snippet,
            )

    def test_whitespace_flattened_quote_is_grounded(self) -> None:
        source = public_source(
            "a",
            "The commenter requests clearer\nimplementation guidance.",
        )
        output = ResponseViewpointOutput(
            questions_misunderstandings=[
                ViewpointFinding(
                    text="One supplied comment requests clearer implementation guidance.",
                    source_type="public_opinion",
                    evidence=[
                        ResponseEvidenceRef(
                            source_id=source.id,
                            quote="The commenter requests clearer implementation guidance.",
                        )
                    ],
                    confidence="high",
                )
            ]
        )

        analysis = build_response_analysis(policy_document(), [source], output)
        claim = analysis.steps[0].claims[0]

        self.assertEqual(len(claim.evidence_ids), 1)
        evidence = analysis.evidence[0]
        self.assertIn("\n", evidence.snippet)
        self.assertEqual(
            source.raw_text[evidence.start_offset:evidence.end_offset],
            evidence.snippet,
        )

    def test_fabricated_quote_isolated_to_finding(self) -> None:
        source = public_source("a", "Real supplied text.")
        good_source = public_source("b", "A real concern appears here.")
        output = ResponseViewpointOutput(
            concerns_objections=[
                ViewpointFinding(
                    text="A grounded concern.",
                    source_type="public_opinion",
                    evidence=[
                        ResponseEvidenceRef(
                            source_id=good_source.id,
                            quote="A real concern appears here.",
                        )
                    ],
                    confidence="high",
                ),
                ViewpointFinding(
                    text="A concern with a broken citation.",
                    source_type="public_opinion",
                    evidence=[
                        ResponseEvidenceRef(
                            source_id=source.id,
                            quote="Fabricated text.",
                        )
                    ],
                    confidence="low",
                ),
            ]
        )

        analysis = build_response_analysis(
            policy_document(),
            [source, good_source],
            output,
        )
        claims = analysis.steps[0].claims

        self.assertEqual(len(claims), 2)
        self.assertTrue(claims[0].evidence_ids)
        self.assertEqual(claims[1].evidence_ids, [])
        self.assertEqual(
            claims[1].verification_status,
            VerificationStatus.NEEDS_HUMAN_REVIEW,
        )
        self.assertIn(
            "Citation integrity is incomplete",
            claims[1].verification_note,
        )
        self.assertIn(
            "Fabricated text.",
            claims[1].verification_note,
        )
        self.assertIn(
            source.id,
            claims[1].verification_note,
        )

    def test_source_type_mismatch_is_rejected(self) -> None:
        source = public_source("a", "Real supplied text.")
        output = ResponseViewpointOutput(
            mixed_neutral=[
                ViewpointFinding(
                    text="A reporting observation.",
                    source_type="factual_reporting",
                    evidence=[
                        ResponseEvidenceRef(
                            source_id=source.id,
                            quote="Real supplied text.",
                        )
                    ],
                    confidence="low",
                )
            ]
        )

        with self.assertRaises(ValueError):
            build_response_analysis(policy_document(), [source], output)

    def test_placeholder_records_are_reported_but_not_clustered_or_analyzed(self) -> None:
        placeholder_a = public_source("p1", "See attached file(s)")
        placeholder_b = public_source("p2", "See attached file(s).")
        substantive = public_source("real", "A substantive response.")
        analysis = build_response_analysis(
            policy_document(),
            [placeholder_a, placeholder_b, substantive],
            ResponseViewpointOutput(),
        )

        note = analysis.steps[0].ai_output
        self.assertIn("received 3 supplied source records", note)
        self.assertIn("analyzed 1 records with retrieved content", note)
        self.assertIn("across 1 unique exact-text clusters", note)
        self.assertIn(
            "Excluded 2 source record(s) from analysis and duplicate clustering",
            note,
        )

    def test_duplicate_records_do_not_inflate_unique_cluster_count(self) -> None:
        source_a = public_source("a", "Repeated exact text.")
        source_b = public_source("b", "Repeated exact text.")
        analysis = build_response_analysis(
            policy_document(),
            [source_a, source_b],
            ResponseViewpointOutput(),
        )

        self.assertIn(
            "received 2 supplied source records; analyzed 2 records with retrieved content across 1 unique exact-text clusters",
            analysis.steps[0].ai_output,
        )


if __name__ == "__main__":
    unittest.main()


class EmailRedactionEdgeCaseTests(unittest.TestCase):
    """
    Regression: a live comment published a named individual's work email
    unredacted because the address ended a sentence, while the source was
    still labelled pii_redaction_status=redacted.
    """

    def test_sentence_final_email_is_redacted(self) -> None:
        text = "Please contact Harley Geiger at athgeiger@venable.com."
        redacted, status = sanitize_public_text(text)
        self.assertNotIn("athgeiger@venable.com", redacted)
        self.assertEqual(status, PiiRedactionStatus.REDACTED)

    def test_multiple_and_punctuated_emails_are_redacted(self) -> None:
        text = "Write to a.b+tag@sub.example.co.uk, or c@d.org."
        redacted, _ = sanitize_public_text(text)
        self.assertNotIn("@", redacted.replace("[REDACTED EMAIL]", ""))

    def test_ordinary_text_is_untouched(self) -> None:
        text = "The rule costs 5@ 10 per unit and mentions no addresses."
        redacted, status = sanitize_public_text(text)
        self.assertEqual(redacted, text)
        self.assertEqual(status, PiiRedactionStatus.NOT_DETECTED)


class ExtractionQualityTests(unittest.TestCase):
    """
    Some PDFs extract with ligatures or with word spacing dropped entirely.
    Ligatures are repairable. Lost spacing is not, so it has to be visible
    rather than silently feeding unusable text to redaction and citation.
    """

    def test_ligatures_are_normalized(self) -> None:
        payload = "the term is de\ufb01ned and e\ufb00ective".encode()
        text = _extract_attachment_payload(payload, "txt")
        self.assertIn("defined", text)
        self.assertIn("effective", text)
        self.assertNotIn("\ufb01", text)

    def test_glued_text_is_detected(self) -> None:
        glued = "byemailingai_reportingonaquarterlybasisasdefinedinparagraph" * 8
        self.assertTrue(extraction_is_degraded(glued))

    def test_ordinary_prose_is_not_flagged(self) -> None:
        prose = "The proposed rule would require quarterly reporting. " * 10
        self.assertFalse(extraction_is_degraded(prose))

    def test_short_text_is_not_flagged(self) -> None:
        self.assertFalse(extraction_is_degraded("See attached file(s)"))

    def test_degraded_attachment_is_marked_for_human_review(self) -> None:
        glued = "wordsallruntogetherwithnospacingatallhere" * 10
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            combined = _combine_comment_and_attachments(
                "See attached file(s)",
                [("Comment letter", glued)],
            )
        self.assertIn("without word spacing", combined)
        self.assertIn("human review", combined)
