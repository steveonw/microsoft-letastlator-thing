import unittest
from datetime import date

from federal_register import NormalizedChunk, NormalizedPolicyDocument
from models import InformationType, StepKind, StepStatus, VerificationStatus
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

    def test_whitespace_flattened_model_quote_is_grounded(self) -> None:
        wrapped_text = (
            "SUPPLEMENTARY INFORMATION:\n\n"
            "The proposal requires quarterly notification\n"
            "by covered persons."
        )
        wrapped_document = NormalizedPolicyDocument(
            document_number="demo-wrap",
            title="Wrapped demo",
            document_type="Proposed Rule",
            raw_text=wrapped_text,
            chunks=[
                NormalizedChunk(
                    id="demo-wrap-chunk-001",
                    sequence=1,
                    heading="SUPPLEMENTARY INFORMATION",
                    text=wrapped_text,
                    start_offset=0,
                    end_offset=len(wrapped_text),
                )
            ],
        )
        output = PolicyInterpreterOutput(
            plain_language=[
                InterpreterFinding(
                    text="The proposal requires quarterly notification.",
                    evidence_quotes=[
                        "The proposal requires quarterly notification by covered persons."
                    ],
                    confidence="high",
                )
            ]
        )

        analysis = build_analysis_from_interpreter_output(wrapped_document, output)
        claim = analysis.steps[0].claims[0]

        self.assertEqual(len(claim.evidence_ids), 1)
        evidence = analysis.evidence[0]
        self.assertIn("\n", evidence.snippet)
        self.assertEqual(
            wrapped_text[evidence.start_offset:evidence.end_offset],
            evidence.snippet,
        )

    def test_nonexistent_model_quote_isolated_to_finding(self) -> None:
        output = PolicyInterpreterOutput(
            plain_language=[
                InterpreterFinding(
                    text="Grounded model claim.",
                    evidence_quotes=[
                        "The proposal requires quarterly notification by covered persons."
                    ],
                    confidence="high",
                ),
                InterpreterFinding(
                    text="Claim with a broken citation.",
                    evidence_quotes=["This quote does not exist."],
                    confidence="low",
                ),
            ]
        )

        analysis = build_analysis_from_interpreter_output(document(), output)
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
            "This quote does not exist.",
            claims[1].verification_note,
        )
        self.assertIn(
            "query not found in source text",
            claims[1].verification_note,
        )

    def test_affected_programs_has_distinct_step_kind(self) -> None:
        analysis = build_analysis_from_interpreter_output(
            document(),
            PolicyInterpreterOutput(),
        )
        affected_programs = next(
            step for step in analysis.steps if step.id == "step-affected-programs"
        )
        self.assertEqual(
            affected_programs.kind,
            StepKind.AFFECTED_PROGRAMS,
        )


if __name__ == "__main__":
    unittest.main()
