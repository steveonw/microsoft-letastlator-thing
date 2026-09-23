import json
import unittest
from datetime import datetime, timezone

from guided_review import edit_current_claim, flag_current_claim
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
from rush_mode import (
    approve_rush_final_review,
    combine_analysis_runs,
    open_rush_step_for_review,
    return_to_rush_final_review,
    run_rush_analysis,
)


RAW_POLICY = "The proposal requires quarterly reports."
RAW_RESPONSE = "I support the reporting schedule."


def base_run(*, response: bool) -> AnalysisRun:
    if response:
        source = Source(
            id="response-1",
            title="Demo response",
            information_type=InformationType.PUBLIC_OPINION,
            raw_text=RAW_RESPONSE,
            pii_redaction_status=PiiRedactionStatus.NOT_DETECTED,
        )
        evidence = Evidence(
            id="evidence-response",
            source_id=source.id,
            snippet=RAW_RESPONSE,
            start_offset=0,
            end_offset=len(RAW_RESPONSE),
            retrieved_at=datetime(2026, 9, 22, tzinfo=timezone.utc),
        )
        claim = Claim(
            id="claim-response",
            text="One supplied response supports the schedule.",
            information_type=InformationType.AI_INTERPRETATION,
            evidence_ids=[evidence.id],
            verification_status=VerificationStatus.NEEDS_HUMAN_REVIEW,
            verification_note="Awaiting verification.",
            confidence="medium",
        )
        step = AnalysisStep(
            id="step-public-response",
            kind=StepKind.PUBLIC_RESPONSE,
            title="Public response",
            claims=[claim],
        )
    else:
        source = Source(
            id="policy-source",
            title="Demo proposal",
            information_type=InformationType.OFFICIAL_POLICY,
            raw_text=RAW_POLICY,
            pii_redaction_status=PiiRedactionStatus.NOT_APPLICABLE,
        )
        evidence = Evidence(
            id="evidence-policy",
            source_id=source.id,
            snippet=RAW_POLICY,
            start_offset=0,
            end_offset=len(RAW_POLICY),
            retrieved_at=datetime(2026, 9, 22, tzinfo=timezone.utc),
        )
        claim = Claim(
            id="claim-policy",
            text="The proposal would require quarterly reports.",
            information_type=InformationType.AI_INTERPRETATION,
            evidence_ids=[evidence.id],
            verification_status=VerificationStatus.NEEDS_HUMAN_REVIEW,
            verification_note="Awaiting verification.",
            confidence="high",
        )
        step = AnalysisStep(
            id="step-stakeholders",
            kind=StepKind.STAKEHOLDERS,
            title="Policy analysis",
            claims=[claim],
        )

    return AnalysisRun(
        id="response-run" if response else "policy-run",
        mode=AnalysisMode.GUIDED,
        policy=Policy(
            id="policy-1",
            title="Demo proposal",
            jurisdiction="United States / federal",
            source_ids=["policy-source"] if not response else [],
        ),
        sources=[source],
        evidence=[evidence],
        steps=[step],
        current_step_id=step.id,
        final_review_status=HumanReviewStatus.NOT_REVIEWED,
    )


class RushModeTests(unittest.TestCase):
    def test_combine_preserves_policy_and_response_sections(self) -> None:
        combined = combine_analysis_runs(
            base_run(response=False),
            base_run(response=True),
        )

        self.assertEqual(combined.mode, AnalysisMode.RUSH)
        self.assertEqual(
            [step.kind for step in combined.steps],
            [StepKind.STAKEHOLDERS, StepKind.PUBLIC_RESPONSE],
        )
        self.assertEqual(
            combined.steps[1].depends_on,
            ["step-stakeholders"],
        )
        self.assertEqual(len(combined.sources), 2)
        self.assertEqual(len(combined.evidence), 2)

    def test_rush_runs_verification_then_stops_for_human_review(self) -> None:
        calls = []

        def model_call(system_prompt: str, user_prompt: str) -> str:
            calls.append(user_prompt)
            return json.dumps(
                {
                    "status": "supported",
                    "explanation": "The cited evidence directly supports the claim.",
                    "narrower_wording": None,
                }
            )

        rushed = run_rush_analysis(
            base_run(response=False),
            base_run(response=True),
            model_call,
        )

        self.assertEqual(len(calls), 2)
        self.assertEqual(rushed.mode, AnalysisMode.RUSH)
        self.assertIsNone(rushed.current_step_id)
        self.assertEqual(
            rushed.final_review_status,
            HumanReviewStatus.IN_REVIEW,
        )
        self.assertEqual(rushed.steps[-1].kind, StepKind.VERIFICATION)
        self.assertTrue(
            all(
                step.human_review.status == HumanReviewStatus.NOT_REVIEWED
                for step in rushed.steps
            )
        )
        self.assertTrue(
            all(
                claim.verification_status == VerificationStatus.SUPPORTED
                for step in rushed.steps
                for claim in step.claims
            )
        )

    def test_saved_rush_section_can_be_opened_edited_and_flagged(self) -> None:
        def model_call(system_prompt: str, user_prompt: str) -> str:
            del system_prompt, user_prompt
            return json.dumps(
                {
                    "status": "supported",
                    "explanation": "Direct support.",
                    "narrower_wording": None,
                }
            )

        rushed = run_rush_analysis(
            base_run(response=False),
            base_run(response=True),
            model_call,
        )
        opened = open_rush_step_for_review(rushed, "step-stakeholders")
        edited = edit_current_claim(
            opened,
            "claim-policy",
            "The proposal would require reports every quarter.",
        )
        flagged = flag_current_claim(
            edited,
            "claim-policy",
            "Review wording before approval.",
        )

        self.assertEqual(flagged.mode, AnalysisMode.RUSH)
        self.assertEqual(flagged.current_step_id, "step-stakeholders")
        self.assertEqual(
            flagged.steps[0].claims[0].original_text,
            "The proposal would require quarterly reports.",
        )
        self.assertIn(
            "claim-policy",
            flagged.steps[0].human_review.flagged_claim_ids,
        )
        self.assertEqual(
            flagged.final_review_status,
            HumanReviewStatus.IN_REVIEW,
        )

    def test_final_approval_requires_explicit_human_action(self) -> None:
        def model_call(system_prompt: str, user_prompt: str) -> str:
            del system_prompt, user_prompt
            return json.dumps(
                {
                    "status": "supported",
                    "explanation": "Direct support.",
                    "narrower_wording": None,
                }
            )

        rushed = run_rush_analysis(
            base_run(response=False),
            base_run(response=True),
            model_call,
        )
        self.assertNotEqual(
            rushed.final_review_status,
            HumanReviewStatus.APPROVED,
        )

        # Approval is refused while any section is unreviewed: "the AI cannot
        # approve its own work" and "approval requires review" are different
        # guarantees, and Rush Mode has to enforce both.
        with self.assertRaises(ValueError) as refused:
            approve_rush_final_review(rushed)
        self.assertIn("unreviewed", str(refused.exception))

        reviewed = rushed.model_copy(deep=True)
        for step in reviewed.steps:
            step.human_review.status = HumanReviewStatus.REVIEWED

        approved = approve_rush_final_review(reviewed)
        self.assertEqual(
            approved.final_review_status,
            HumanReviewStatus.APPROVED,
        )

    def test_unreviewed_approval_requires_acknowledgement_and_is_recorded(
        self,
    ) -> None:
        def model_call(system_prompt: str, user_prompt: str) -> str:
            del system_prompt, user_prompt
            return json.dumps(
                {
                    "status": "supported",
                    "explanation": "Direct support.",
                    "narrower_wording": None,
                }
            )

        rushed = run_rush_analysis(
            base_run(response=False),
            base_run(response=True),
            model_call,
        )

        approved = approve_rush_final_review(rushed, acknowledge_unreviewed=True)
        self.assertEqual(
            approved.final_review_status,
            HumanReviewStatus.APPROVED,
        )

        # The shortcut must leave a trace on every section it skipped.
        for step in approved.steps:
            self.assertTrue(
                any("acknowledged override" in note for note in step.human_review.notes),
                f"{step.id} has no override note",
            )

    def test_return_to_final_review_clears_open_section(self) -> None:
        def model_call(system_prompt: str, user_prompt: str) -> str:
            del system_prompt, user_prompt
            return json.dumps(
                {
                    "status": "supported",
                    "explanation": "Direct support.",
                    "narrower_wording": None,
                }
            )

        rushed = run_rush_analysis(
            base_run(response=False),
            base_run(response=True),
            model_call,
        )
        opened = open_rush_step_for_review(rushed, "step-public-response")
        returned = return_to_rush_final_review(opened)

        self.assertIsNone(returned.current_step_id)
        self.assertEqual(
            returned.final_review_status,
            HumanReviewStatus.IN_REVIEW,
        )


if __name__ == "__main__":
    unittest.main()
