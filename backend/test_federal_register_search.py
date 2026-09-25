"""Phase 9 intake: Federal Register search and conservative docket detection."""

import unittest
from urllib.parse import parse_qs, urlparse

from federal_register import (
    classify_docket_id,
    detect_docket,
    detect_document_docket,
    looks_like_document_number,
    normalize_document,
    search_documents,
)


REAL_DOCKET = {
    "document_number": "2024-20529",
    "title": "Establishment of Reporting Requirements for the Development of Advanced Artificial Intelligence Models and Computing Clusters",
    "type": "Proposed Rule",
    "action": "Proposed rule; request for comment.",
    "abstract": "BIS proposes reporting requirements for advanced AI models.",
    "agencies": [
        {"name": "Industry and Security Bureau"},
        {"name": "Commerce Department"},
    ],
    "publication_date": "2024-09-11",
    "comments_close_on": "2024-10-11",
    "docket_ids": ["Docket No. 240905-0231"],
    "regulation_id_numbers": ["0694-AJ55"],
    "regulations_dot_gov_info": {
        "docket_id": "BIS-2024-0047",
        "comments_count": 50,
    },
    "html_url": "https://www.federalregister.gov/documents/2024/09/11/2024-20529/x",
}

CATCH_ALL_ONLY = {
    "document_number": "2024-10070",
    "title": "Agency Information Collection Activities; Comment Request",
    "type": "Notice",
    "agencies": [{"name": "Labor Department"}],
    "publication_date": "2024-05-09",
    "docket_ids": [],
    "regulation_id_numbers": [],
    "regulations_dot_gov_info": {
        "docket_id": "DOL_FRDOC_0001",
        "comments_count": 1,
    },
}

PTO_INTERNAL_REFERENCE = {
    "document_number": "2025-00001",
    "title": "Patent Office Notice",
    "type": "Notice",
    "agencies": [{"name": "Patent and Trademark Office"}],
    "publication_date": "2025-01-02",
    "docket_ids": ["Docket No. PTO-P-2025-0014"],
    "regulation_id_numbers": [],
}


class FakeFederalRegister:
    def __init__(self, results, count=None):
        self.payload = {
            "count": count if count is not None else len(results),
            "results": results,
        }
        self.urls = []

    def __call__(self, url, *, timeout=30):
        del timeout
        self.urls.append(url)
        return self.payload


class DocumentNumberTests(unittest.TestCase):
    def test_document_numbers_are_recognized(self):
        for value in ("2024-20529", " 2024-20529 ", "E9-12345", "04-1234"):
            self.assertTrue(looks_like_document_number(value), value)

    def test_search_words_are_not_document_numbers(self):
        for value in (
            "overtime exemption",
            "AI reporting 2024",
            "BIS-2024-0047",
            "0694-AJ55",
            "",
        ):
            self.assertFalse(looks_like_document_number(value), value)


class DocketDetectionTests(unittest.TestCase):
    def test_classification(self):
        self.assertEqual(classify_docket_id("BIS-2024-0047"), "regulations_gov")
        self.assertEqual(
            classify_docket_id("EPA-HQ-OAR-2021-0317"),
            "regulations_gov",
        )
        self.assertEqual(classify_docket_id("DOL_FRDOC_0001"), "catch_all")
        self.assertEqual(classify_docket_id("240905-0231"), "agency_reference")

    def test_explicit_regulations_pointer_is_safe_to_prefill(self):
        detection = detect_docket(REAL_DOCKET)
        self.assertEqual(detection.status, "single")
        self.assertEqual(detection.docket_id, "BIS-2024-0047")
        self.assertIn("explicit official Regulations.gov pointer", detection.note)

    def test_catch_all_docket_is_never_prefilled(self):
        detection = detect_docket(CATCH_ALL_ONLY)
        self.assertEqual(detection.status, "none")
        self.assertIsNone(detection.docket_id)
        self.assertEqual(detection.excluded[0].kind, "catch_all")

    def test_federal_register_docket_id_alone_is_not_auto_fetched(self):
        detection = detect_docket(PTO_INTERNAL_REFERENCE)
        self.assertEqual(detection.status, "none")
        self.assertIsNone(detection.docket_id)
        self.assertEqual(
            detection.excluded[0].docket_id,
            "PTO-P-2025-0014",
        )
        self.assertEqual(
            detection.excluded[0].kind,
            "unverified_reference",
        )
        self.assertIn("will not auto-load comments", detection.note)

    def test_normalized_document_preserves_explicit_regulations_docket(self):
        document = normalize_document(
            REAL_DOCKET,
            "SUMMARY: Example source text for testing.",
        )
        self.assertEqual(
            document.regulations_dot_gov_docket_id,
            "BIS-2024-0047",
        )
        detection = detect_document_docket(document)
        self.assertEqual(detection.status, "single")
        self.assertEqual(detection.docket_id, "BIS-2024-0047")


class SearchTests(unittest.TestCase):
    def test_defaults_to_rules_and_proposed_rules(self):
        fake = FakeFederalRegister([REAL_DOCKET])
        search_documents("ai reporting", get_json=fake)
        query = parse_qs(urlparse(fake.urls[0]).query)
        self.assertEqual(
            query["conditions[type][]"],
            ["RULE", "PRORULE"],
        )
        self.assertEqual(query["conditions[term]"], ["ai reporting"])
        self.assertEqual(query["per_page"], ["8"])
        self.assertIn("regulations_dot_gov_info", query["fields[]"])

    def test_notice_search_is_explicit(self):
        fake = FakeFederalRegister([CATCH_ALL_ONLY])
        result = search_documents(
            "comment request",
            document_types=["NOTICE"],
            get_json=fake,
        )
        self.assertEqual(result.document_types, ["NOTICE"])
        self.assertEqual(result.candidates[0].docket.status, "none")

    def test_candidates_carry_selection_metadata(self):
        fake = FakeFederalRegister(
            [REAL_DOCKET, CATCH_ALL_ONLY],
            count=955,
        )
        result = search_documents(
            "  ai   reporting ",
            document_types=["PRORULE", "NOTICE"],
            get_json=fake,
        )
        self.assertEqual(result.query, "ai reporting")
        self.assertEqual(result.total_count, 955)
        first, second = result.candidates
        self.assertEqual(first.document_number, "2024-20529")
        self.assertEqual(
            first.agency_names,
            ["Industry and Security Bureau", "Commerce Department"],
        )
        self.assertEqual(first.comments_close_on.isoformat(), "2024-10-11")
        self.assertEqual(first.regulation_id_numbers, ["0694-AJ55"])
        self.assertEqual(first.comments_count, 50)
        self.assertEqual(first.docket.docket_id, "BIS-2024-0047")
        self.assertEqual(second.docket.status, "none")

    def test_results_are_capped_at_limit(self):
        items = [
            dict(REAL_DOCKET, document_number=f"2024-{number:05d}")
            for number in range(12)
        ]
        result = search_documents(
            "ai",
            limit=8,
            get_json=FakeFederalRegister(items),
        )
        self.assertEqual(len(result.candidates), 8)

    def test_bad_input_is_rejected_before_request(self):
        fake = FakeFederalRegister([])
        with self.assertRaises(ValueError):
            search_documents("   ", get_json=fake)
        with self.assertRaises(ValueError):
            search_documents("ai", limit=0, get_json=fake)
        with self.assertRaises(ValueError):
            search_documents("ai", document_types=["MEMO"], get_json=fake)
        self.assertEqual(fake.urls, [])


if __name__ == "__main__":
    unittest.main()
