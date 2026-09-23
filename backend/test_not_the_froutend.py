import unittest

from models import HumanReviewStatus, StepStatus
from run_not_the_froutend import DemoState


class NotTheFroutendDemoTests(unittest.TestCase):
    def test_demo_state_runs_chunk9_flow(self) -> None:
        state = DemoState()

        updated = state.reanalyze(
            "step-two",
            "Covered providers are explicitly identified by the policy.",
        )
        step_map = {step.id: step for step in updated.steps}

        self.assertEqual(step_map["step-two"].version, 3)
        self.assertEqual(step_map["step-two"].status, StepStatus.DRAFT)
        self.assertEqual(step_map["step-three"].status, StepStatus.NEEDS_REFRESH)
        self.assertEqual(step_map["step-four"].status, StepStatus.NEEDS_REFRESH)
        self.assertEqual(step_map["step-sibling"].status, StepStatus.VERIFIED)

        with self.assertRaisesRegex(ValueError, "cannot refresh before dependencies"):
            state.refresh("step-four")

        state.refresh("step-three")
        state.refresh("step-four")
        state.review("step-two")
        state.review("step-three")
        state.review("step-four")

        briefed = state.brief()
        brief = briefed.steps[-1]

        self.assertEqual(brief.id, "step-draft-brief")
        self.assertEqual(
            briefed.final_review_status,
            HumanReviewStatus.IN_REVIEW,
        )
        self.assertIn(
            "[claim-two] Covered providers are explicitly identified by the policy.",
            brief.ai_output,
        )


if __name__ == "__main__":
    unittest.main()
