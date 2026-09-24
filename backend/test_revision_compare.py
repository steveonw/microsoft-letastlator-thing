import unittest
from datetime import date
from unittest.mock import patch

from federal_register import normalize_document
from revision_compare import compare_documents, link_existing_claims
from run_full_stack_guide import GuideState, POLICY_TEXT, make_guided_demo


def policy_doc(
    number: str,
    publication_date: str,
    text: str,
):
    return normalize_document(
        {
            "document_number": number,
            "title": f"Test policy {number}",
            "type": "Proposed Rule",
            "publication_date": publication_date,
            "regulation_id_numbers": ["TEST-0001"],
            "citation": "90 FR 100",
            "html_url": f"https://www.federalregister.gov/d/{number}",
        },
        text,
    )


class RevisionCompareTests(unittest.TestCase):
    def test_comparison_classifies_changed_added_and_removed_language(self) -> None:
        older = policy_doc(
            "2025-10000",
            "2025-01-01",
            (
                "Reports are due by March 31 and apply above 10^20 operations.\n\n"
                "Covered companies must maintain records.\n\n"
                "This paragraph is removed in the later version."
            ),
        )
        newer = policy_doc(
            "2026-20000",
            "2026-01-01",
            (
                "Reports are due by April 15 and apply above 10^22 operations.\n\n"
                "Covered companies and individual providers must maintain records.\n\n"
                "A new quarterly certification is required."
            ),
        )

        comparison = compare_documents(older, newer)

        self.assertEqual(comparison.from_document.document_number, "2025-10000")
        self.assertEqual(comparison.to_document.document_number, "2026-20000")
        self.assertEqual(comparison.shared_rins, ["TEST-0001"])
        self.assertGreaterEqual(comparison.changed_count, 2)
        self.assertGreaterEqual(comparison.added_count, 1)
        self.assertGreaterEqual(comparison.removed_count, 1)

        tags = {tag for change in comparison.changes for tag in change.tags}
        self.assertIn("deadline/date", tags)
        self.assertIn("threshold/number", tags)
        self.assertIn("stakeholder-scope language", tags)

        for change in comparison.changes:
            if change.before_text:
                self.assertIn("chars ", change.before_locator)
                self.assertEqual(
                    change.before_url,
                    "https://www.federalregister.gov/d/2025-10000",
                )
            if change.after_text:
                self.assertIn("chars ", change.after_locator)
                self.assertEqual(
                    change.after_url,
                    "https://www.federalregister.gov/d/2026-20000",
                )

    def test_document_order_follows_publication_date(self) -> None:
        newer = policy_doc("2026-20000", "2026-01-01", "New text.")
        older = policy_doc("2025-10000", "2025-01-01", "Old text.")

        comparison = compare_documents(newer, older)

        self.assertEqual(comparison.from_document.document_number, "2025-10000")
        self.assertEqual(comparison.to_document.document_number, "2026-20000")

    def test_changed_source_range_links_existing_claim_ids(self) -> None:
        older = policy_doc("2025-10000", "2025-01-01", POLICY_TEXT)
        newer = policy_doc(
            "2026-20000",
            "2026-01-01",
            POLICY_TEXT.replace("March 31", "April 15"),
        )
        analysis = make_guided_demo()

        comparison = link_existing_claims(
            compare_documents(older, newer),
            analysis,
            analyzed_document_number=older.document_number,
        )

        self.assertIn("claim-major", comparison.potentially_affected_claim_ids)
        affected_changes = [
            change
            for change in comparison.changes
            if "claim-major" in change.potentially_affected_claim_ids
        ]
        self.assertTrue(affected_changes)

    def test_fuzzy_matching_shortlists_candidates_instead_of_all_pairs(self) -> None:
        paragraphs_before = [
            f"Section {i} requires covered providers to file report {i} within 30 days."
            for i in range(60)
        ]
        paragraphs_after = [
            (
                f"Section {i} requires covered providers to file report {i} within "
                + ("45 days." if i % 7 == 0 else "30 days.")
            )
            for i in range(60)
        ]
        older = policy_doc(
            "2025-10000",
            "2025-01-01",
            "\n\n".join(paragraphs_before),
        )
        newer = policy_doc(
            "2026-20000",
            "2026-01-01",
            "\n\n".join(paragraphs_after),
        )

        calls = 0

        class CountingMatcher:
            def __init__(self, *args, **kwargs):
                nonlocal calls
                calls += 1
                from difflib import SequenceMatcher as RealMatcher
                self._inner = RealMatcher(*args, **kwargs)

            def ratio(self):
                return self._inner.ratio()

            def get_opcodes(self):
                return self._inner.get_opcodes()

        with patch("revision_compare.SequenceMatcher", CountingMatcher):
            comparison = compare_documents(older, newer)

        self.assertGreater(comparison.changed_count, 0)
        self.assertLess(
            calls,
            400,
            "candidate-first matcher should avoid near all-pairs fuzzy comparison",
        )

    def test_guide_state_fetches_second_document_without_rerunning_analysis(self) -> None:
        state = GuideState()
        state.document = policy_doc("2025-10000", "2025-01-01", POLICY_TEXT)
        state.analysis = make_guided_demo()
        before_run_id = state.analysis.id
        newer = policy_doc(
            "2026-20000",
            "2026-01-01",
            POLICY_TEXT.replace("March 31", "April 15"),
        )

        with patch(
            "run_full_stack_guide.fetch_and_normalize",
            return_value=newer,
        ) as fetch:
            payload = state.compare_revision("2026-20000")

        fetch.assert_called_once_with("2026-20000")
        self.assertTrue(payload["available"])
        self.assertEqual(payload["to_document"]["document_number"], "2026-20000")
        self.assertEqual(state.analysis.id, before_run_id)
        self.assertIn("claim-major", payload["potentially_affected_claim_ids"])


if __name__ == "__main__":
    unittest.main()
