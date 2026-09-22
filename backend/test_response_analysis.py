import unittest
from datetime import date, datetime, timezone

from federal_register import NormalizedChunk, NormalizedPolicyDocument
from models import InformationType, PiiRedactionStatus, StepKind, VerificationStatus
from response_sources import (
    ResponseRecord,
    _comment_record_from_detail,
    duplicate_cluster_id,
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

    def test_source_keeps_response_type_and_duplicate_cluster(self) -> None:
        source = public_source("a", "A response statement.")

        self.assertEqual(source.information_type, InformationType.PUBLIC_OPINION)
        self.assertTrue(source.duplicate_cluster_id)
        self.assertEqual(
            source.pii_redaction_status,
            PiiRedactionStatus.NOT_DETECTED,
        )


class ResponseAnalystTests(unittest.TestCase):
    def test_prompt_contains_only_response_material(self) -> None:
        source = public_source("a", "A supplied response statement.")

        prompt = build_response_viewpoint_prompt([source])

        self.assertIn("response-a", prompt)
        self.assertIn("type=public_opinion", prompt)
        self.assertIn("A supplied response statement.", prompt)
        self.assertNotIn(POLICY_TEXT, prompt)

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
        self.assertIn("Citation integrity is incomplete", claims[1].verification_note)

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

    def test_duplicate_records_do_not_inflate_unique_cluster_count(self) -> None:
        source_a = public_source("a", "Repeated exact text.")
        source_b = public_source("b", "Repeated exact text.")
        analysis = build_response_analysis(
            policy_document(),
            [source_a, source_b],
            ResponseViewpointOutput(),
        )

        self.assertIn(
            "analyzed 2 supplied source records across 1 unique exact-text clusters",
            analysis.steps[0].ai_output,
        )


if __name__ == "__main__":
    unittest.main()
