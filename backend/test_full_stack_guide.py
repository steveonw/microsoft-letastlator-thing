import json
import unittest

from models import HumanReviewStatus, StepStatus
from run_full_stack_guide import GuideState


class FullStackGuideTests(unittest.TestCase):
    def test_provider_secrets_are_process_only_and_not_returned(self) -> None:
        state = GuideState()
        secret = "test-secret-do-not-serialize"

        status = state.provider.configure(
            {
                "kind": "openrouter",
                "api_key": secret,
                "model": "openrouter/free",
                "regulations_api_key": "test-regulations-secret",
            }
        )

        encoded_status = json.dumps(status)
        encoded_analysis = state.analysis.model_dump_json()

        self.assertNotIn(secret, encoded_status)
        self.assertNotIn(secret, encoded_analysis)
        self.assertNotIn("test-regulations-secret", encoded_status)
        self.assertTrue(status["has_api_key"])
        self.assertTrue(status["has_regulations_api_key"])
        self.assertEqual(status["credentials_storage"], "process_memory_only")

        state.provider.clear()
        self.assertFalse(state.provider.status()["has_api_key"])

    def test_guided_actions_use_authoritative_analysis_state(self) -> None:
        state = GuideState()

        started = state.guided_begin()
        self.assertEqual(started.current_step_id, "step-policy-understanding")

        claim_id = started.steps[0].claims[0].id
        edited = state.guided_edit(
            claim_id,
            "The policy creates an annual compliance recordkeeping duty.",
        )
        self.assertEqual(edited.steps[0].version, 2)

        verified = state.guided_verify(claim_id)
        self.assertEqual(
            verified.steps[0].claims[0].verification_status.value,
            "supported",
        )

        advanced = state.guided_next()
        self.assertEqual(advanced.current_step_id, "step-major-provisions")
        self.assertEqual(
            advanced.steps[0].human_review.status,
            HumanReviewStatus.REVIEWED,
        )

    def test_rush_stops_at_final_human_review(self) -> None:
        state = GuideState()
        rushed = state.run_rush()

        self.assertEqual(rushed.mode.value, "rush")
        self.assertIsNone(rushed.current_step_id)
        self.assertEqual(
            rushed.final_review_status,
            HumanReviewStatus.IN_REVIEW,
        )

        approved = state.rush_approve()
        self.assertEqual(
            approved.final_review_status,
            HumanReviewStatus.APPROVED,
        )

    def test_chunk9_reference_flow_refreshes_only_dependents(self) -> None:
        state = GuideState()
        for step in state.analysis.steps:
            step.status = StepStatus.VERIFIED
            step.human_review.status = HumanReviewStatus.REVIEWED
        state.analysis.final_review_status = HumanReviewStatus.APPROVED

        changed = state.reanalyze(
            "step-major-provisions",
            "Licensed providers have an annual March 31 reporting deadline.",
        )
        step_map = {step.id: step for step in changed.steps}

        self.assertEqual(step_map["step-major-provisions"].version, 2)
        self.assertEqual(step_map["step-stakeholders"].status, StepStatus.NEEDS_REFRESH)
        self.assertEqual(step_map["step-policy-understanding"].status, StepStatus.VERIFIED)

        with self.assertRaisesRegex(ValueError, "steps need refresh"):
            state.brief()

        state.refresh("step-stakeholders")
        state.review_reanalysis("step-major-provisions")
        state.review_reanalysis("step-stakeholders")

        briefed = state.brief()
        self.assertEqual(briefed.steps[-1].id, "step-draft-brief")
        self.assertEqual(
            briefed.final_review_status,
            HumanReviewStatus.IN_REVIEW,
        )


if __name__ == "__main__":
    unittest.main()
