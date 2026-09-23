import unittest
from datetime import date, datetime, timezone

from evidence import (
    build_chunk3_demo_analysis,
    evidence_for_query,
    find_quote_span,
    source_from_federal_register,
)
from federal_register import NormalizedChunk, NormalizedPolicyDocument
from models import InformationType, StepStatus, VerificationStatus


RAW_TEXT = (
    "Background\n\n"
    "This proposed rule discusses advanced artificial intelligence models "
    "and computing clusters.\n\n"
    "The agency requests comment on reporting requirements."
)


def make_document() -> NormalizedPolicyDocument:
    return NormalizedPolicyDocument(
        document_number="2024-20529",
        title="AI reporting proposal",
        document_type="Proposed Rule",
        action="Proposed rule; request for comment",
        agency_names=["Bureau of Industry and Security"],
        publication_date=date(2024, 9, 11),
        docket_ids=["240905-0231"],
        regulation_id_numbers=["0694-AJ55"],
        citation="89 FR 73612",
        html_url="https://www.federalregister.gov/d/2024-20529",
        raw_text=RAW_TEXT,
        chunks=[
            NormalizedChunk(
                id="2024-20529-chunk-001",
                sequence=1,
                heading="Background",
                text=RAW_TEXT,
                start_offset=0,
                end_offset=len(RAW_TEXT),
            )
        ],
    )


class EvidenceLayerTests(unittest.TestCase):
    def test_source_uses_shared_contract(self) -> None:
        source = source_from_federal_register(make_document())

        self.assertEqual(source.id, "fr-2024-20529")
        self.assertEqual(source.information_type, InformationType.OFFICIAL_POLICY)
        self.assertEqual(source.raw_text, RAW_TEXT)

    def test_evidence_offsets_reproduce_exact_snippet(self) -> None:
        document = make_document()
        evidence = evidence_for_query(
            document,
            "artificial intelligence",
            context_chars=35,
            retrieved_at=datetime(2026, 9, 22, tzinfo=timezone.utc),
        )

        self.assertEqual(
            document.raw_text[evidence.start_offset:evidence.end_offset],
            evidence.snippet,
        )
        self.assertIn("artificial intelligence", evidence.snippet.lower())
        self.assertIn("89 FR 73612", evidence.locator)
        self.assertIn("2024-20529-chunk-001", evidence.locator)

    def test_zero_context_keeps_complete_query(self) -> None:
        document = make_document()
        evidence = evidence_for_query(
            document,
            "artificial intelligence",
            context_chars=0,
            retrieved_at=datetime(2026, 9, 22, tzinfo=timezone.utc),
        )

        self.assertIn("artificial intelligence", evidence.snippet.lower())
        self.assertEqual(
            document.raw_text[evidence.start_offset:evidence.end_offset],
            evidence.snippet,
        )

    def test_case_insensitive_match_keeps_exact_offsets(self) -> None:
        document = make_document()
        evidence = evidence_for_query(
            document,
            "ARTIFICIAL INTELLIGENCE",
            context_chars=0,
            retrieved_at=datetime(2026, 9, 22, tzinfo=timezone.utc),
        )

        self.assertIn("artificial intelligence", evidence.snippet.lower())
        self.assertEqual(
            document.raw_text[evidence.start_offset:evidence.end_offset],
            evidence.snippet,
        )

    def test_whitespace_variation_matches_source_and_keeps_exact_offsets(self) -> None:
        text = "The reporting requirement applies to advanced artificial\nintelligence models."
        document = NormalizedPolicyDocument(
            document_number="whitespace-demo",
            title="Whitespace demo",
            raw_text=text,
            chunks=[
                NormalizedChunk(
                    id="whitespace-demo-chunk-001",
                    sequence=1,
                    heading="Demo",
                    text=text,
                    start_offset=0,
                    end_offset=len(text),
                )
            ],
        )

        evidence = evidence_for_query(
            document,
            "advanced artificial intelligence models.",
            context_chars=0,
            retrieved_at=datetime(2026, 9, 22, tzinfo=timezone.utc),
        )

        self.assertEqual(
            evidence.snippet,
            "advanced artificial\nintelligence models.",
        )
        self.assertEqual(
            text[evidence.start_offset:evidence.end_offset],
            evidence.snippet,
        )

    def test_hard_wrap_after_hyphen_matches_without_changing_offsets(self) -> None:
        text = "computational operations (e.g., integer or floating-\npoint operations)."
        query = "computational operations (e.g., integer or floating-point operations)."

        start, end = find_quote_span(text, query)

        self.assertEqual(text[start:end], text)
        self.assertIn("floating-\npoint", text[start:end])

    def test_hard_wrap_after_slash_matches_without_changing_offsets(self) -> None:
        text = "per second (OP/\ns) for AI training, without sparsity."
        query = "per second (OP/s) for AI training, without sparsity."

        start, end = find_quote_span(text, query)

        self.assertEqual(text[start:end], text)
        self.assertIn("OP/\ns", text[start:end])

    def test_hard_wrap_tolerance_does_not_accept_changed_punctuation(self) -> None:
        text = "The threshold is 10[supcaret]26 computational operations."
        with self.assertRaises(ValueError):
            find_quote_span(
                text,
                "The threshold is 10[supcaret]26 computational operations;",
            )

    def test_hard_wrap_tolerance_does_not_treat_ellipsis_as_wildcard(self) -> None:
        text = "BIS welcomes comments on the notification schedule and storage."
        with self.assertRaises(ValueError):
            find_quote_span(
                text,
                "BIS welcomes comments ... storage.",
            )

    def test_query_can_span_chunk_boundary(self) -> None:
        text = "Alpha policy phrase crosses boundary here."
        document = NormalizedPolicyDocument(
            document_number="demo",
            title="Boundary demo",
            raw_text=text,
            chunks=[
                NormalizedChunk(
                    id="demo-chunk-001",
                    sequence=1,
                    heading="Section A",
                    text=text[:20],
                    start_offset=0,
                    end_offset=20,
                ),
                NormalizedChunk(
                    id="demo-chunk-002",
                    sequence=2,
                    heading="Section B",
                    text=text[20:],
                    start_offset=20,
                    end_offset=len(text),
                ),
            ],
        )

        evidence = evidence_for_query(
            document,
            "phrase crosses",
            context_chars=0,
            retrieved_at=datetime(2026, 9, 22, tzinfo=timezone.utc),
        )

        self.assertIn("phrase crosses", evidence.snippet)
        self.assertEqual(
            text[evidence.start_offset:evidence.end_offset],
            evidence.snippet,
        )

    def test_missing_query_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            evidence_for_query(make_document(), "phrase that is not present")

    def test_claim_points_to_real_evidence_and_validates(self) -> None:
        analysis = build_chunk3_demo_analysis(
            make_document(),
            retrieved_at=datetime(2026, 9, 22, tzinfo=timezone.utc),
        )

        claim = analysis.steps[0].claims[0]
        evidence = analysis.evidence[0]

        self.assertEqual(claim.evidence_ids, [evidence.id])
        self.assertEqual(
            claim.verification_status,
            VerificationStatus.NEEDS_HUMAN_REVIEW,
        )
        self.assertEqual(analysis.steps[0].status, StepStatus.DRAFT)
        self.assertEqual(evidence.source_id, analysis.sources[0].id)
        self.assertEqual(
            analysis.sources[0].raw_text[
                evidence.start_offset:evidence.end_offset
            ],
            evidence.snippet,
        )


if __name__ == "__main__":
    unittest.main()


class TypographicToleranceTests(unittest.TestCase):
    """
    Live sources and model output disagree about typography, not wording.
    Federal Register text uses TeX-style ``quotes'', PDF extraction yields
    curly quotes and en dashes, and a model quoting either writes ASCII.
    """

    def test_ascii_quotes_match_curly_quotes(self) -> None:
        source = 'The rule defines \u201ccovered provider\u201d in section two.'
        start, end = find_quote_span(source, '"covered provider"')
        self.assertEqual(source[start:end], "\u201ccovered provider\u201d")

    def test_ascii_quotes_match_tex_pairs(self) -> None:
        source = "the term ``covered person'' means any entity"
        start, end = find_quote_span(source, '"covered person" means')
        self.assertEqual(source[start:end], "``covered person'' means")

    def test_ascii_apostrophe_matches_curly(self) -> None:
        source = "the agency\u2019s estimate of burden"
        start, end = find_quote_span(source, "the agency's estimate")
        self.assertEqual(source[start:end], "the agency\u2019s estimate")

    def test_hyphen_matches_en_dash(self) -> None:
        source = "a dual\u2013use foundation model"
        start, end = find_quote_span(source, "dual-use foundation model")
        self.assertEqual(source[start:end], "dual\u2013use foundation model")

    def test_wording_differences_still_fail(self) -> None:
        source = "The rule applies to covered providers."
        with self.assertRaises(ValueError):
            find_quote_span(source, "The rule applies to licensed providers.")
