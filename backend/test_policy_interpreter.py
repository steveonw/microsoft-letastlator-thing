import unittest
from datetime import date

from federal_register import NormalizedChunk, NormalizedPolicyDocument
from models import InformationType, StepStatus, VerificationStatus
from policy_interpreter import (
    InterpreterFinding,
    PolicyInterpreterOutput,
    build_analysis_from_interpreter_output,
    build_policy_interpreter_prompt,
)


RAW_TEXT = (
    "SUPPLEMENTARY INFORMATION:\n\n"
    "Background\n\n"
    "The proposal requires quarterly notification by covered persons.\n\n"
    "I. Reporting Schedule\n\n"
    "Quarterly reports are due on listed dates."
)


def document() -> NormalizedPolicyDocument:
    return NormalizedPolicyDocument(
        document_number="demo-1",
        title="Demo proposed rule",
        document_type="Proposed Rule",
        action="Proposed rule; request for comment",
        agency_names=["Demo Agency"],
        publication_date=date(2026, 1, 2),
        citation="99 FR 100",
        html_url="https://example.gov/demo",
        raw_text=RAW_TEXT,
        chunks=[
            NormalizedChunk(
                id="demo-1-chunk-001",
                sequence=1,
                heading="Background",
                text=RAW_TEXT,
                start_offset=0,
                end_offset=len(RAW_TEXT),
            )
        ],
    )


class PolicyInterpreterTests(unittest.TestCase):
    def test_prompt_preserves_policy_status_and_source_boundaries(self) -> None:
        prompt = build_policy_interpreter_prompt(document())

        self.assertIn("Document type: Proposed Rule", prompt)
        self.assertIn("OFFICIAL SOURCE TEXT START", prompt)
        self.assertIn("demo-1-chunk-001", prompt)
        self.assertIn("quarterly notification", prompt)

    def test_structured_output_becomes_draft_evidence_linked_claims(self) -> None:
        output = PolicyInterpreterOutput(
            plain_language=[
                InterpreterFinding(
                    text="The proposal describes quarterly notification.",
                    evidence_quotes=[
                        "The proposal requires quarterly notification by covered persons."
                    ],
                    confidence="high",
                )
            ],
            major_provisions=[
                InterpreterFinding(
                    text="The source describes listed reporting dates.",
                    evidence_quotes=[
                        "Quarterly reports are due on listed dates."
                    ],
                    confidence="high",
                )
            ],
            stakeholders=[
                InterpreterFinding(
                    text="Covered persons are directly described.",
                    evidence_quotes=[
                        "The proposal requires quarterly notification by covered persons."
                    ],
                    confidence="medium",
                )
            ],
        )

        analysis = build_analysis_from_interpreter_output(document(), output)

        self.assertEqual(len(analysis.steps), 4)
        self.assertTrue(analysis.evidence)

        for step in analysis.steps:
            self.assertEqual(step.status, StepStatus.DRAFT)
            for claim in step.claims:
                self.assertEqual(
                    claim.information_type,
                    InformationType.AI_INTERPRETATION,
                )
                self.assertEqual(
                    claim.verification_status,
                    VerificationStatus.NEEDS_HUMAN_REVIEW,
                )
                self.assertTrue(claim.evidence_ids)

        for item in analysis.evidence:
            source = analysis.sources[0]
            self.assertEqual(
                source.raw_text[item.start_offset:item.end_offset],
                item.snippet,
            )

    def test_nonexistent_model_quote_is_rejected(self) -> None:
        output = PolicyInterpreterOutput(
            plain_language=[
                InterpreterFinding(
                    text="Unsupported model claim.",
                    evidence_quotes=["This quote does not exist."],
                    confidence="low",
                )
            ]
        )

        with self.assertRaises(ValueError):
            build_analysis_from_interpreter_output(document(), output)


if __name__ == "__main__":
    unittest.main()
