import json
import unittest
from unittest.mock import patch

from models import HumanReviewStatus, StepStatus
from run_full_stack_guide import GuideState, make_rush_inputs


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

    def test_live_policy_load_becomes_authoritative_state(self) -> None:
        state = GuideState()
        state.provider.kind = "openrouter"
        state.provider.api_key = "fake-model-key"
        state.provider.model = "openrouter/free"
        policy_run, _ = make_rush_inputs()
        fake_document = object()

        with (
            patch(
                "run_full_stack_guide.fetch_and_normalize",
                return_value=fake_document,
            ) as fetch,
            patch(
                "run_full_stack_guide.run_policy_interpreter",
                return_value=policy_run,
            ) as interpret,
        ):
            loaded = state.load_policy("2024-20529")

        fetch.assert_called_once_with("2024-20529")
        interpret.assert_called_once()
        self.assertIs(state.document, fake_document)
        self.assertEqual(state.policy_analysis.policy.id, policy_run.policy.id)
        self.assertEqual(loaded.policy.id, policy_run.policy.id)
        self.assertIsNone(loaded.current_step_id)

    def test_live_comment_load_uses_memory_only_regulations_key(self) -> None:
        state = GuideState()
        state.provider.kind = "openrouter"
        state.provider.api_key = "fake-model-key"
        state.provider.model = "openrouter/free"
        state.provider.regulations_api_key = "regulations-secret"
        policy_run, response_run = make_rush_inputs()
        state.document = object()
        state.policy_analysis = policy_run

        fake_record = object()
        fake_source = response_run.sources[0]

        with (
            patch(
                "run_full_stack_guide.fetch_comments_for_docket",
                return_value=[fake_record],
            ) as fetch_comments,
            patch(
                "run_full_stack_guide.source_from_response_record",
                return_value=fake_source,
            ),
            patch(
                "run_full_stack_guide.run_response_viewpoint_analyst",
                return_value=response_run,
            ),
        ):
            loaded = state.load_comments("BIS-2024-0047", max_comments=7)

        fetch_comments.assert_called_once_with(
            "BIS-2024-0047",
            api_key="regulations-secret",
            max_comments=7,
        )
        self.assertIs(state.response_analysis, response_run)
        kinds = {step.kind.value for step in loaded.steps}
        self.assertIn("policy_understanding", kinds)
        self.assertIn("public_response", kinds)
        self.assertNotIn("regulations-secret", loaded.model_dump_json())

    def test_live_source_requires_real_model_provider(self) -> None:
        state = GuideState()
        with self.assertRaisesRegex(ValueError, "requires OpenRouter"):
            state.load_policy("2024-20529")

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
