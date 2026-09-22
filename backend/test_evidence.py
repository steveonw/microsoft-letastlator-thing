import unittest
from datetime import date, datetime, timezone

from evidence import (
    build_chunk3_demo_analysis,
    evidence_for_query,
    source_from_federal_register,
)
from federal_register import NormalizedChunk, NormalizedPolicyDocument
from models import InformationType


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
        self.assertEqual(evidence.source_id, analysis.sources[0].id)
        self.assertEqual(
            analysis.sources[0].raw_text[
                evidence.start_offset:evidence.end_offset
            ],
            evidence.snippet,
        )


if __name__ == "__main__":
    unittest.main()
