from __future__ import annotations

import unittest
from datetime import date, datetime, timezone
from unittest.mock import patch

from federal_register import DocketDetection, SearchCandidate, normalize_document
from policy_intake import (
    IntakePlan,
    PolicyTraceProject,
    bounded_preview_excerpt,
    estimate_comparison_workload,
    related_document_suggestions,
    search_federal_register,
    validate_project,
)
from policy_status import FederalRegisterDocumentRef, PolicyStatusSnapshot


def make_document(
    number: str,
    *,
    title: str = "Example Artificial Intelligence Reporting Rule",
    text_size: int = 1200,
    publication_date: date = date(2024, 9, 11),
):
    raw_text = ("Official Federal Register source text. " * 1000)[:text_size]
    return normalize_document(
        {
            "document_number": number,
            "title": title,
            "type": "Proposed Rule",
            "publication_date": publication_date.isoformat(),
            "agency_names": ["Example Agency"],
            "docket_ids": ["Docket No. EXAMPLE-2024-0001"],
            "regulation_id_numbers": ["1234-AA01"],
            "regulations_dot_gov_info": {
                "docket_id": "EXAMPLE-2024-0001",
            },
            "html_url": f"https://www.federalregister.gov/d/{number}",
        },
        raw_text,
    )


class PolicyIntakeSearchTests(unittest.TestCase):
    def test_search_defaults_to_rule_types(self) -> None:
        candidate = SearchCandidate(
            document_number="2024-10001",
            title="AI Reporting Proposal",
            document_type="Proposed Rule",
            publication_date=date(2024, 1, 2),
            agency_names=["Example Agency"],
            docket=DocketDetection(
                status="none",
                note="No Regulations.gov comment docket was detected.",
            ),
        )

        with patch("policy_intake.search_documents") as search:
            search.return_value.candidates = [candidate]
            results = search_federal_register("AI reporting", limit=2)

        self.assertEqual([item.document_number for item in results], ["2024-10001"])
        _, kwargs = search.call_args
        self.assertEqual(kwargs["document_types"], ["RULE", "PRORULE"])
        self.assertEqual(kwargs["limit"], 2)

    def test_search_can_widen_to_notices(self) -> None:
        with patch("policy_intake.search_documents") as search:
            search.return_value.candidates = []
            search_federal_register(
                "AI reporting",
                include_notices=True,
            )

        _, kwargs = search.call_args
        self.assertEqual(
            kwargs["document_types"],
            ["RULE", "PRORULE", "NOTICE"],
        )

    def test_empty_search_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "document number or search words"):
            search_federal_register("   ")


class RelatedDocumentSuggestionTests(unittest.TestCase):
    def test_same_rin_documents_are_strong_suggestions(self) -> None:
        document = make_document("2024-10001")
        status = PolicyStatusSnapshot(
            available=True,
            checked_at=datetime(2026, 9, 25, tzinfo=timezone.utc),
            rin="1234-AA01",
            federal_register_documents=[
                FederalRegisterDocumentRef(
                    document_number="2024-10001",
                    title=document.title,
                    document_type="Proposed Rule",
                    publication_date=date(2024, 9, 11),
                ),
                FederalRegisterDocumentRef(
                    document_number="2025-20002",
                    title="Example Artificial Intelligence Reporting Final Rule",
                    document_type="Rule",
                    publication_date=date(2025, 1, 10),
                ),
            ],
            status_label="Final Rule",
            freshness_message="Later action found.",
        )

        suggestions = related_document_suggestions(document, status)

        self.assertEqual(suggestions[0].document_number, "2025-20002")
        self.assertEqual(suggestions[0].relationship_strength, "strong")
        self.assertIn("same RIN: 1234-AA01", suggestions[0].reasons)
        self.assertIn("published later than selected document", suggestions[0].reasons)


    def test_same_agency_without_title_overlap_is_not_suggested(self) -> None:
        document = make_document(
            "2025-19674",
            title="American AI Exports Program",
            publication_date=date(2025, 10, 28),
        )
        document.agency_names = ["Department of Commerce"]
        status = PolicyStatusSnapshot(
            available=False,
            checked_at=datetime(2026, 9, 25, tzinfo=timezone.utc),
            rin=None,
            federal_register_documents=[],
            status_label="Status check unavailable",
            freshness_message="No RIN available.",
        )
        unrelated = SearchCandidate(
            document_number="2026-01059",
            title="Streamlining Export Controls for Drone Exports",
            document_type="Rule",
            publication_date=date(2026, 1, 21),
            agency_names=["Department of Commerce"],
            docket=DocketDetection(
                status="none",
                note="No Regulations.gov comment docket was detected.",
            ),
        )

        with patch(
            "policy_intake.search_federal_register",
            return_value=[unrelated],
        ):
            suggestions = related_document_suggestions(document, status)

        self.assertEqual(suggestions, [])


class ComparisonWorkloadTests(unittest.TestCase):
    def test_large_comparison_requires_one_confirmation(self) -> None:
        primary = make_document("2024-10001", text_size=1000)
        comparison = make_document("2025-20002", text_size=3500)

        with patch("policy_intake.fetch_and_normalize", return_value=comparison):
            estimate, fetched = estimate_comparison_workload(
                primary,
                comparison.document_number,
            )

        self.assertEqual(fetched.document_number, comparison.document_number)
        self.assertEqual(estimate.workload, "large")
        self.assertEqual(estimate.confirmation_steps, 1)
        self.assertGreaterEqual(estimate.relative_size, 3)

    def test_very_large_comparison_requires_two_confirmations(self) -> None:
        primary = make_document("2024-10001", text_size=1000)
        comparison = make_document("2025-20002", text_size=6000)

        with patch("policy_intake.fetch_and_normalize", return_value=comparison):
            estimate, _ = estimate_comparison_workload(
                primary,
                comparison.document_number,
            )

        self.assertEqual(estimate.workload, "very_large")
        self.assertEqual(estimate.confirmation_steps, 2)


class ProjectFileTests(unittest.TestCase):
    def test_project_schema_restores_intake_choices_without_credentials(self) -> None:
        project = PolicyTraceProject(
            saved_at=datetime(2026, 9, 25, tzinfo=timezone.utc),
            search_query="AI reporting",
            include_notices=True,
            primary_document_number="2024-10001",
            intake_plan=IntakePlan(
                docket_id="EXAMPLE-2024-0001",
                max_comments=12,
                comment_sampling_method="random",
                comment_sampling_seed=48213,
                max_articles=8,
                comparison_document_number="2025-20002",
                include_comparison=True,
                report_standard="balanced",
            ),
            excluded_media_claim_ids=["claim-news-demo"],
        )

        validated = validate_project(project.model_dump(mode="json"))

        self.assertEqual(validated.policytrace_project_schema, 1)
        self.assertTrue(validated.include_notices)
        self.assertTrue(validated.intake_plan.include_comparison)
        self.assertEqual(validated.intake_plan.report_standard.value, "balanced")
        self.assertEqual(validated.intake_plan.comment_sampling_method, "random")
        self.assertEqual(validated.intake_plan.comment_sampling_seed, 48213)
        self.assertEqual(validated.excluded_media_claim_ids, ["claim-news-demo"])

    def test_legacy_project_without_sampling_fields_keeps_earliest_behavior(self) -> None:
        value = {
            "policytrace_project_schema": 1,
            "saved_at": "2026-09-25T00:00:00Z",
            "search_query": "AI",
            "include_notices": False,
            "primary_document_number": "2024-10001",
            "intake_plan": {
                "docket_id": "EXAMPLE-2024-0001",
                "max_comments": 12,
            },
            "excluded_media_claim_ids": [],
        }

        validated = validate_project(value)

        self.assertEqual(
            validated.intake_plan.comment_sampling_method,
            "earliest",
        )
        self.assertIsNone(validated.intake_plan.comment_sampling_seed)

    def test_project_schema_rejects_embedded_credentials(self) -> None:
        value = {
            "policytrace_project_schema": 1,
            "saved_at": "2026-09-25T00:00:00Z",
            "search_query": "AI",
            "primary_document_number": "2024-10001",
            "intake_plan": {},
            "excluded_media_claim_ids": [],
            "api_key": "must-not-be-stored",
        }

        with self.assertRaises(Exception):
            validate_project(value)


class PreviewExcerptTests(unittest.TestCase):
    def test_preview_excerpt_is_bounded(self) -> None:
        document = make_document("2024-10001", text_size=4000)
        excerpt = bounded_preview_excerpt(document, max_chars=1800)

        self.assertEqual(len(excerpt), 1800)


if __name__ == "__main__":
    unittest.main()
