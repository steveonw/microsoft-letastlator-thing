"""
Contract tests for the app UI.

These assert the sequences frontend/app/app.js actually performs, because the
UI bugs found in review were all integration bugs: each endpoint worked, and
the order the UI called them in did not. Unit tests on the endpoints would not
have caught any of them.
"""

from __future__ import annotations

import unittest

from models import AnalysisMode, HumanReviewStatus, StepStatus
from run_full_stack_guide import GuideState


class AppStartFlowTests(unittest.TestCase):
    def test_rush_start_runs_the_pipeline_exactly_once(self) -> None:
        """
        reset(mode="rush") already runs Rush. The UI must use that result
        rather than calling run_rush again, or every model call happens twice.
        """
        state = GuideState()
        calls: list[str] = []
        original = state.run_rush

        def counted() -> object:
            calls.append("run")
            return original()

        state.run_rush = counted  # type: ignore[method-assign]

        started = state.reset("rush")

        self.assertEqual(len(calls), 1)
        self.assertEqual(started.mode, AnalysisMode.RUSH)
        self.assertEqual(started.final_review_status, HumanReviewStatus.IN_REVIEW)

    def test_guided_start_needs_an_explicit_begin(self) -> None:
        state = GuideState()
        loaded = state.reset("guided")
        self.assertIsNone(loaded.current_step_id)

        begun = state.guided_begin(None)
        self.assertIsNotNone(begun.current_step_id)


class RushPerClaimActionTests(unittest.TestCase):
    """
    Rush ends with no section open, but the per-claim actions are the Guided
    ones and need a current section. The UI opens the section first.
    """

    def test_flag_fails_without_opening_the_section(self) -> None:
        state = GuideState()
        rushed = state.reset("rush")
        self.assertIsNone(rushed.current_step_id)

        claim_id = rushed.steps[0].claims[0].id
        with self.assertRaises(ValueError):
            state.guided_flag(claim_id, None)

    def test_flag_works_after_opening_the_section(self) -> None:
        state = GuideState()
        rushed = state.reset("rush")
        step = rushed.steps[0]

        state.rush_open(step.id)
        flagged = state.guided_flag(step.claims[0].id, "needs a second look")

        self.assertEqual(flagged.current_step_id, step.id)
        self.assertTrue(
            any(
                "second look" in note
                for note in flagged.steps[0].human_review.notes
            )
        )

    def test_verify_one_claim_does_not_mark_the_whole_section_reviewed(
        self,
    ) -> None:
        """
        "Check this finding" must check one finding. Marking the section
        reviewed is a separate, separately labelled action.
        """
        state = GuideState()
        rushed = state.reset("rush")
        step = rushed.steps[0]

        state.rush_open(step.id)
        verified = state.guided_verify(step.claims[0].id)

        reviewed_step = next(s for s in verified.steps if s.id == step.id)
        self.assertNotEqual(
            reviewed_step.human_review.status,
            HumanReviewStatus.REVIEWED,
        )


class RushEditTargetsSelectedClaimTests(unittest.TestCase):
    """
    Re-analysis used to rewrite claims[0] regardless of which finding the
    reviewer selected, so editing the second finding silently rewrote the
    first.
    """

    def _multi_claim_state(self) -> tuple[GuideState, str, list[str]]:
        state = GuideState()
        state.reset("rush")

        step = next(s for s in state.analysis.steps if len(s.claims) >= 1)
        if len(step.claims) < 2:
            # Duplicate the existing claim so the section has two findings.
            extra = step.claims[0].model_copy(deep=True)
            extra.id = f"{step.claims[0].id}-second"
            extra.text = "Second finding in this section."
            step.claims.append(extra)

        return state, step.id, [claim.id for claim in step.claims]

    def test_editing_the_second_claim_leaves_the_first_alone(self) -> None:
        state, step_id, claim_ids = self._multi_claim_state()
        step = next(s for s in state.analysis.steps if s.id == step_id)
        first_text = step.claims[0].text

        updated = state.reanalyze(
            step_id,
            "Reviewer rewrote the second finding.",
            claim_id=claim_ids[1],
        )

        edited_step = next(s for s in updated.steps if s.id == step_id)
        self.assertEqual(edited_step.claims[0].text, first_text)
        self.assertEqual(
            edited_step.claims[1].text,
            "Reviewer rewrote the second finding.",
        )
        # Whether the edit is also recorded as human-authored belongs to the
        # edit-trail work, not to this UI contract, so it is not asserted here.

    def test_unknown_claim_id_is_rejected(self) -> None:
        state, step_id, _ = self._multi_claim_state()
        with self.assertRaises(ValueError):
            state.reanalyze(step_id, "text", claim_id="claim-not-here")


class RefreshFlowTests(unittest.TestCase):
    def test_edit_marks_dependents_stale_and_refresh_clears_them(self) -> None:
        state = GuideState()
        rushed = state.reset("rush")
        first = rushed.steps[0]

        edited = state.reanalyze(
            first.id,
            "Reviewer rewrite.",
            claim_id=first.claims[0].id,
        )
        stale = [s.id for s in edited.steps if s.status == StepStatus.NEEDS_REFRESH]
        self.assertTrue(stale, "editing a section should invalidate its dependents")

        refreshed = state.refresh(stale[0])
        still_stale = [
            s.id
            for s in refreshed.steps
            if s.id == stale[0] and s.status == StepStatus.NEEDS_REFRESH
        ]
        self.assertFalse(still_stale)


if __name__ == "__main__":
    unittest.main()


class ProviderConfigurationTests(unittest.TestCase):
    """
    Foundry is the contest-required path and has the strictest contract:
    endpoint, model, and exactly one of an API key or a bearer token. The UI
    sends every one of these fields, so the contract is pinned here.
    """

    def test_foundry_accepts_endpoint_model_and_api_key(self) -> None:
        state = GuideState()
        status = state.provider.configure(
            {
                "kind": "foundry",
                "endpoint": "https://example.services.ai.azure.com/models",
                "model": "gpt-4o-mini",
                "api_key": "secret",
            }
        )
        self.assertEqual(status["kind"], "foundry")
        self.assertEqual(status["endpoint"], "https://example.services.ai.azure.com/models")
        self.assertTrue(status["has_api_key"])
        self.assertFalse(status["has_bearer_token"])

    def test_foundry_accepts_a_bearer_token_instead(self) -> None:
        state = GuideState()
        status = state.provider.configure(
            {
                "kind": "foundry",
                "endpoint": "https://example.services.ai.azure.com/models",
                "model": "gpt-4o-mini",
                "bearer_token": "token",
            }
        )
        self.assertTrue(status["has_bearer_token"])
        self.assertFalse(status["has_api_key"])

    def test_foundry_without_an_endpoint_is_rejected(self) -> None:
        state = GuideState()
        with self.assertRaises(ValueError) as refused:
            state.provider.configure(
                {"kind": "foundry", "model": "gpt-4o-mini", "api_key": "secret"}
            )
        self.assertIn("endpoint", str(refused.exception).lower())

    def test_foundry_rejects_both_credentials(self) -> None:
        """Exactly one, so supplying both fails as surely as supplying neither."""
        state = GuideState()
        for credentials in (
            {"api_key": "secret", "bearer_token": "token"},
            {},
        ):
            with self.assertRaises(ValueError):
                state.provider.configure(
                    {
                        "kind": "foundry",
                        "endpoint": "https://example.services.ai.azure.com/models",
                        "model": "gpt-4o-mini",
                        **credentials,
                    }
                )

    def test_credentials_are_never_echoed_back(self) -> None:
        state = GuideState()
        status = state.provider.configure(
            {
                "kind": "foundry",
                "endpoint": "https://example.services.ai.azure.com/models",
                "model": "gpt-4o-mini",
                "api_key": "super-secret-value",
            }
        )
        self.assertNotIn("super-secret-value", str(status))
        self.assertEqual(status["credentials_storage"], "process_memory_only")

    def test_openrouter_fills_in_its_own_defaults(self) -> None:
        state = GuideState()
        status = state.provider.configure({"kind": "openrouter", "api_key": "k"})
        self.assertTrue(status["model"])
        self.assertTrue(status["base_url"])


class GuidedNavigationAndInvalidationTests(unittest.TestCase):
    def test_explicit_navigation_controls_which_section_next_accepts(self) -> None:
        state = GuideState()
        state.reset("guided")
        first_id = state.analysis.steps[0].id
        second_id = state.analysis.steps[1].id

        state.guided_begin(first_id)
        state.guided_begin(second_id)
        advanced = state.guided_next()

        first = next(step for step in advanced.steps if step.id == first_id)
        second = next(step for step in advanced.steps if step.id == second_id)
        self.assertEqual(first.human_review.status, HumanReviewStatus.IN_REVIEW)
        self.assertEqual(second.human_review.status, HumanReviewStatus.REVIEWED)

    def test_guided_edit_invalidates_reviewed_dependents(self) -> None:
        state = GuideState()
        state.reset("guided")
        first = state.guided_begin(None).steps[0]

        state.guided_next()
        state.guided_next()
        finished = state.guided_next()
        self.assertIsNone(finished.current_step_id)

        state.guided_begin(first.id)
        edited = state.guided_edit(first.claims[0].id, "Human corrected wording.")

        downstream = edited.steps[1:]
        self.assertTrue(downstream)
        self.assertTrue(
            all(step.status == StepStatus.NEEDS_REFRESH for step in downstream)
        )
        self.assertTrue(
            all(
                step.human_review.status == HumanReviewStatus.NOT_REVIEWED
                for step in downstream
            )
        )


class FinalApprovalFlowTests(unittest.TestCase):
    def test_rush_section_review_preserves_rush_mode(self) -> None:
        state = GuideState()
        rushed = state.reset("rush")
        reviewed = state.review_reanalysis(rushed.steps[0].id)

        self.assertEqual(reviewed.mode, AnalysisMode.RUSH)
        self.assertEqual(
            reviewed.steps[0].human_review.status,
            HumanReviewStatus.REVIEWED,
        )

    def test_guided_final_brief_requires_all_sections_and_can_be_approved(self) -> None:
        state = GuideState()
        state.reset("guided")
        state.guided_begin(None)
        state.guided_next()
        state.guided_next()
        state.guided_next()

        briefed = state.brief()
        self.assertEqual(briefed.final_review_status, HumanReviewStatus.IN_REVIEW)

        approved = state.approve_final_brief()
        self.assertEqual(approved.final_review_status, HumanReviewStatus.APPROVED)
        brief = next(step for step in approved.steps if step.kind.value == "draft_brief")
        self.assertEqual(brief.human_review.status, HumanReviewStatus.APPROVED)

    def test_final_approval_refuses_unreviewed_sections(self) -> None:
        state = GuideState()
        state.reset("guided")
        state.guided_begin(None)
        state.guided_next()
        state.brief()

        with self.assertRaises(ValueError) as refused:
            state.approve_final_brief()
        self.assertIn("unreviewed", str(refused.exception))
