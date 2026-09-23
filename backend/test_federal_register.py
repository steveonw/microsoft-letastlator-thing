import unittest

from evidence import find_quote_span
from federal_register import chunk_text, normalize_document


SAMPLE_METADATA = {
    "document_number": "2024-20529",
    "title": "Establishment of Reporting Requirements for the Development of Advanced Artificial Intelligence Models and Computing Clusters",
    "type": "Proposed Rule",
    "action": "Proposed rule; request for comment",
    "agency_names": ["Bureau of Industry and Security"],
    "publication_date": "2024-09-11",
    "comments_close_on": "2024-10-11",
    "docket_ids": ["240905-0231"],
    "regulation_id_numbers": ["0694-AJ55"],
    "citation": "89 FR 73612",
    "cfr_references": [{"title": 15, "part": 702}],
    "html_url": "https://www.federalregister.gov/d/2024-20529",
    "pdf_url": "https://www.govinfo.gov/example.pdf",
    "regulations_dot_gov_url": "https://www.regulations.gov/docket/BIS-2024-0047",
    "raw_text_url": "https://www.govinfo.gov/example.txt",
}

SAMPLE_TEXT = """DEPARTMENT OF COMMERCE

Background

This proposed rule concerns reporting about advanced artificial intelligence models and computing clusters.

Discussion of the Proposed Rule

Covered entities would provide notifications when specified technical thresholds are met.

Request for Comments

The agency requests comment on notification timing, collection methods, and technical thresholds.
"""


class FederalRegisterNormalizerTests(unittest.TestCase):
    def test_metadata_and_text_normalize(self) -> None:
        document = normalize_document(SAMPLE_METADATA, SAMPLE_TEXT, max_chunk_chars=500)

        self.assertEqual(document.document_number, "2024-20529")
        self.assertEqual(document.publication_date.isoformat(), "2024-09-11")
        self.assertEqual(document.comments_close_on.isoformat(), "2024-10-11")
        self.assertEqual(document.docket_ids, ["240905-0231"])
        self.assertTrue(document.chunks)

    def test_chunk_offsets_round_trip(self) -> None:
        text = ("Background\n\n" + ("AI policy sentence. " * 80)).strip()
        chunks = chunk_text("demo", text, max_chars=500)

        for chunk in chunks:
            self.assertEqual(
                text[chunk.start_offset:chunk.end_offset],
                chunk.text,
            )

    def test_realistic_headings_are_carried_into_chunks(self) -> None:
        text = (
            "SUPPLEMENTARY INFORMATION:\n\n"
            + ("Background material. " * 40)
            + "\n\nI. Quarterly Notification Schedule\n\n"
            + ("Covered U.S. persons must report. " * 40)
        )
        chunks = chunk_text("demo", text, max_chars=500)

        self.assertTrue(all(chunk.heading for chunk in chunks))
        self.assertTrue(
            any("Quarterly Notification Schedule" in chunk.heading for chunk in chunks)
        )

    def test_regulations_dot_gov_url_is_inferred(self) -> None:
        metadata = dict(SAMPLE_METADATA)
        metadata["regulations_dot_gov_url"] = None
        text = SAMPLE_TEXT + (
            "\nADDRESSES: The regulations.gov ID for this proposed rule is: "
            "BIS-2024-0047.\n"
        )

        document = normalize_document(metadata, text, max_chunk_chars=500)

        self.assertEqual(
            str(document.regulations_dot_gov_url),
            "https://www.regulations.gov/docket/BIS-2024-0047",
        )

    def test_chunk_ids_are_stable_and_ordered(self) -> None:
        text = ("Paragraph one. " * 70) + "\n\n" + ("Paragraph two. " * 70)
        chunks = chunk_text("2024-20529", text, max_chars=500)

        self.assertEqual(chunks[0].id, "2024-20529-chunk-001")
        self.assertEqual(
            [chunk.sequence for chunk in chunks],
            list(range(1, len(chunks) + 1)),
        )


if __name__ == "__main__":
    unittest.main()


class SuperscriptNormalizationTests(unittest.TestCase):
    """
    Federal Register plain text writes exponents as "10[supcaret]26". A model
    reading that quotes "10^26", so without normalization every citation to a
    computational-threshold definition fails to match.
    """

    def test_supcaret_marker_becomes_caret(self) -> None:
        raw = "training run using more than 10[supcaret]26 computational operations"
        document = normalize_document(
            {"title": "t", "document_number": "d"},
            raw,
        )
        self.assertIn("10^26", document.raw_text)
        self.assertNotIn("[supcaret]", document.raw_text)

    def test_model_style_exponent_quote_matches_after_normalization(self) -> None:
        raw = "any cluster with more than 10[supcaret]20 operations per second"
        document = normalize_document(
            {"title": "t", "document_number": "d"},
            raw,
        )
        start, end = find_quote_span(document.raw_text, "more than 10^20 operations")
        self.assertEqual(document.raw_text[start:end], "more than 10^20 operations")
