import json
import unittest
from datetime import datetime, timezone

from guided_review import (
    begin_guided_review,
    clarify_current_step,
    edit_current_claim,
    evidence_for_current_claim,
    flag_current_claim,
    next_guided_step,
    verify_current_claim,
)
from models import (
    AnalysisMode,
    AnalysisRun,
    AnalysisStep,
    Claim,
    Evidence,
    HumanReviewStatus,
    InformationType,
    PiiRedactionStatus,
    Policy,
    Source,
    StepKind,
    VerificationStatus,
)


RAW_TEXT = "Quarterly notifications are required. Responses are due within 30 days."


def demo_analysis() -> AnalysisRun:
    source = Source(
        id="source-1",
        title="Official proposal",
        information_type=InformationType.OFFICIAL_POLICY,
        raw_text=RAW_TEXT,
        pii_redaction_status=PiiRedactionStatus.NOT_APPLICABLE,
    )
    evidence = Evidence(
        id="evidence-1",
        source_id=source.id,
        snippet="Quarterly notifications are required.",
        locator="Section 1",
        start_offset=0,
        end_offset=len("Quarterly notifications are required."),
        retrieved_at=datetime(2026, 9, 22, tzinfo=timezone.utc),
    )
    claim = Claim(
        id="claim-1",
        text="Notifications would be required quarterly.",
        information_type=InformationType.AI_INTERPRETATION,
        evidence_ids=[evidence.id],
        verification_status=VerificationStatus.SUPPORTED,
        verification_note="Semantic verification: direct support.",
        confidence="high",
    )
    second_claim = Claim(
        id="claim-2",
        text="Responses would be due within 30 days.",
        information_type=InformationType.AI_INTERPRETATION,
        evidence_ids=[evidence.id],
        verification_status=VerificationStatus.NEEDS_HUMAN_REVIEW,
        verification_note="Awaiting review.",
        confidence="medium",
    )
    step_one = AnalysisStep(
        id="step-one",
        kind=StepKind.POLICY_UNDERSTANDING,
        title="Policy understanding",
        claims=[claim],
    )
    step_two = AnalysisStep(
        id="step-two",
        kind=StepKind.MAJOR_PROVISIONS,
        title="Major provisions",
        depends_on=[step_one.id],
        claims=[second_claim],
    )
    return AnalysisRun(
        id="guided-run",
        mode=AnalysisMode.GUIDED,
        policy=Policy(
            id="policy-1",
            title="Demo policy",
            jurisdiction="United States / federal",
            source_ids=[source.id],
        ),
        sources=[source],
        evidence=[evidence],
        steps=[step_one, step_two],
        current_step_id=step_two.id,
        final_review_status=HumanReviewStatus.NOT_REVIEWED,
    )


class GuidedReviewTests(unittest.TestCase):
    def test_begin_guided_review_starts_at_first_unreviewed_step(self) -> None:
        analysis = begin_guided_review(demo_analysis())

        self.assertEqual(analysis.current_step_id, "step-one")
        self.assertEqual(
            analysis.steps[0].human_review.status,
            HumanReviewStatus.IN_REVIEW,
        )

    def test_clarify_persists_note_without_advancing(self) -> None:
        analysis = begin_guided_review(demo_analysis())
        clarified = clarify_current_step(
            analysis,
            "Treat this as a proposed requirement, not current law.",
        )

        self.assertEqual(clarified.current_step_id, "step-one")
        self.assertIn(
            "Clarification: Treat this as a proposed requirement, not current law.",
            clarified.steps[0].human_review.notes,
        )

    def test_edit_preserves_original_and_requires_reverification(self) -> None:
        analysis = begin_guided_review(demo_analysis())
        edited = edit_current_claim(
            analysis,
            "claim-1",
            "The proposal would require quarterly notifications.",
        )
        claim = edited.steps[0].claims[0]

        self.assertEqual(
            claim.original_text,
            "Notifications would be required quarterly.",
        )
        self.assertEqual(
            claim.text,
            "The proposal would require quarterly notifications.",
        )
        self.assertEqual(
            claim.information_type,
            InformationType.HUMAN_INTERPRETATION,
        )
        self.assertEqual(
            claim.verification_status,
            VerificationStatus.NEEDS_HUMAN_REVIEW,
        )
        self.assertIn(
            claim.id,
            edited.steps[0].human_review.edited_claim_ids,
        )
        self.assertEqual(edited.current_step_id, "step-one")

    def test_edit_cannot_modify_claim_outside_current_step(self) -> None:
        analysis = begin_guided_review(demo_analysis())

        with self.assertRaisesRegex(ValueError, "not part of current step"):
            edit_current_claim(analysis, "claim-2", "Changed elsewhere.")

    def test_flag_persists_without_advancing(self) -> None:
        analysis = begin_guided_review(demo_analysis())
        flagged = flag_current_claim(
            analysis,
            "claim-1",
            "Needs a second look.",
        )

        self.assertEqual(flagged.current_step_id, "step-one")
        self.assertEqual(
            flagged.steps[0].human_review.flagged_claim_ids,
            ["claim-1"],
        )
        self.assertIn(
            "Flagged claim-1: Needs a second look.",
            flagged.steps[0].human_review.notes,
        )

    def test_show_sources_returns_exact_evidence_and_source(self) -> None:
        analysis = begin_guided_review(demo_analysis())
        pairs = evidence_for_current_claim(analysis, "claim-1")

        self.assertEqual(len(pairs), 1)
        evidence, source = pairs[0]
        self.assertEqual(evidence.id, "evidence-1")
        self.assertEqual(source.id, "source-1")
        self.assertEqual(
            source.raw_text[evidence.start_offset:evidence.end_offset],
            evidence.snippet,
        )

    def test_verify_selected_claim_does_not_advance(self) -> None:
        analysis = begin_guided_review(demo_analysis())

        def model_call(system_prompt: str, user_prompt: str) -> str:
            self.assertIn("Evidence Verifier", system_prompt)
            self.assertIn("Claim ID: claim-1", user_prompt)
            return json.dumps(
                {
                    "status": "partially_supported",
                    "explanation": "The evidence supports quarterly timing but not every detail.",
                    "narrower_wording": "Quarterly notifications are required.",
                }
            )

        verified = verify_current_claim(analysis, "claim-1", model_call)
        claim = verified.steps[0].claims[0]

        self.assertEqual(
            claim.verification_status,
            VerificationStatus.PARTIALLY_SUPPORTED,
        )
        self.assertIn("Suggested narrower wording:", claim.verification_note)
        self.assertEqual(verified.current_step_id, "step-one")

    def test_verify_selected_claim_recovers_chatty_json(self) -> None:
        analysis = begin_guided_review(demo_analysis())

        def model_call(system_prompt: str, user_prompt: str) -> str:
            del system_prompt, user_prompt
            return (
                "Sure! Here is the JSON:\n"
                '{"status":"supported","explanation":"Direct support.",'
                '"narrower_wording":null}'
            )

        verified = verify_current_claim(analysis, "claim-1", model_call)

        self.assertEqual(
            verified.steps[0].claims[0].verification_status,
            VerificationStatus.SUPPORTED,
        )
        self.assertEqual(verified.current_step_id, "step-one")

    def test_verify_selected_claim_routes_bad_reply_to_human_review(self) -> None:
        analysis = begin_guided_review(demo_analysis())

        def model_call(system_prompt: str, user_prompt: str) -> str:
            del system_prompt, user_prompt
            return "not json"

        verified = verify_current_claim(analysis, "claim-1", model_call)
        claim = verified.steps[0].claims[0]

        self.assertEqual(
            claim.verification_status,
            VerificationStatus.NEEDS_HUMAN_REVIEW,
        )
        self.assertIn("unparseable or schema-invalid", claim.verification_note)
        self.assertEqual(verified.current_step_id, "step-one")

    def test_verify_provider_failure_stays_in_human_review(self) -> None:
        analysis = begin_guided_review(demo_analysis())

        def model_call(system_prompt: str, user_prompt: str) -> str:
            del system_prompt, user_prompt
            raise RuntimeError("OpenRouter request timed out after retrying")

        verified = verify_current_claim(analysis, "claim-1", model_call)
        claim = verified.steps[0].claims[0]

        self.assertEqual(
            claim.verification_status,
            VerificationStatus.NEEDS_HUMAN_REVIEW,
        )
        self.assertIn("model provider failed", claim.verification_note)
        self.assertEqual(
            verified.steps[0].human_review.status,
            HumanReviewStatus.IN_REVIEW,
        )

    def test_only_next_advances_and_marks_current_reviewed(self) -> None:
        analysis = begin_guided_review(demo_analysis())
        clarified = clarify_current_step(analysis, "Keep proposed-rule wording.")

        advanced = next_guided_step(clarified)

        self.assertEqual(advanced.current_step_id, "step-two")
        self.assertEqual(
            advanced.steps[0].human_review.status,
            HumanReviewStatus.REVIEWED,
        )
        self.assertEqual(
            advanced.steps[1].human_review.status,
            HumanReviewStatus.IN_REVIEW,
        )

    def test_next_after_last_step_finishes_guided_steps_without_final_approval(self) -> None:
        analysis = begin_guided_review(demo_analysis())
        analysis = next_guided_step(analysis)
        completed = next_guided_step(analysis)

        self.assertIsNone(completed.current_step_id)
        self.assertEqual(
            completed.steps[1].human_review.status,
            HumanReviewStatus.REVIEWED,
        )
        self.assertEqual(
            completed.final_review_status,
            HumanReviewStatus.NOT_REVIEWED,
        )


if __name__ == "__main__":
    unittest.main()
