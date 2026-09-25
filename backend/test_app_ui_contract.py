"""
Contract tests for the app UI.

These assert the sequences frontend/app/app.js actually performs, because the
UI bugs found in review were all integration bugs: each endpoint worked, and
the order the UI called them in did not. Unit tests on the endpoints would not
have caught any of them.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import run_full_stack_guide as full_stack
from models import AnalysisMode, HumanReviewStatus, StepKind, StepStatus
from run_full_stack_guide import GuideState
from response_sources import CommentFetchFailure


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



class TrustUxCleanupTests(unittest.TestCase):
    def test_user_facing_verification_notes_do_not_expose_chunk_jargon(self) -> None:
        policy_path = full_stack.ROOT / "backend" / "policy_interpreter.py"
        evidence_path = full_stack.ROOT / "backend" / "evidence.py"
        combined = (
            policy_path.read_text(encoding="utf-8")
            + "\n"
            + evidence_path.read_text(encoding="utf-8")
        )

        self.assertNotIn("deferred to Chunk 6", combined)
        self.assertNotIn("verified until Chunk 6", combined)
        self.assertIn(
            "Citation integrity checked. Semantic support still needs verification.",
            combined,
        )

    def test_response_ui_language_does_not_claim_minority_prevalence(self) -> None:
        analyst_path = full_stack.ROOT / "backend" / "response_viewpoint_analyst.py"
        source = analyst_path.read_text(encoding="utf-8")

        self.assertIn("Distinct / conflicting viewpoints", source)
        self.assertNotIn("Minority / conflicting viewpoints", source)
        self.assertIn("Do not label a viewpoint as a minority", source)

    def test_guided_final_state_suppresses_redundant_accept_action(self) -> None:
        app_path = full_stack.ROOT / "frontend" / "app" / "app.js"
        source = app_path.read_text(encoding="utf-8")

        self.assertIn('const reviewed = ["reviewed", "approved"].includes', source)
        self.assertIn("if (!(reviewed && allContentReviewed()))", source)
        self.assertIn('add("Build final brief"', source)

    def test_phase_seven_build_marker_is_visible(self) -> None:
        index_path = full_stack.ROOT / "frontend" / "app" / "index.html"
        html = index_path.read_text(encoding="utf-8")
        self.assertIn(">build 27<", html)

    def test_analysis_prompts_request_atomic_findings(self) -> None:
        policy_path = full_stack.ROOT / "backend" / "policy_interpreter.py"
        response_path = full_stack.ROOT / "backend" / "response_viewpoint_analyst.py"
        policy_source = policy_path.read_text(encoding="utf-8")
        response_source = response_path.read_text(encoding="utf-8")

        self.assertIn("Keep each finding atomic", policy_source)
        self.assertIn("Keep each finding atomic", response_source)


class FinalOutputSeparationTests(unittest.TestCase):
    def test_product_ui_has_separate_leadership_and_audit_views(self) -> None:
        index_path = full_stack.ROOT / "frontend" / "app" / "index.html"
        app_path = full_stack.ROOT / "frontend" / "app" / "app.js"
        html = index_path.read_text(encoding="utf-8")
        source = app_path.read_text(encoding="utf-8")

        self.assertIn('id="show-leadership"', html)
        self.assertIn('id="show-audit"', html)
        self.assertIn("Leadership Report", html)
        self.assertIn("Evidence Audit Log", html)
        self.assertIn("/api/audit-log", source)
        self.assertIn("reportView", source)

    def test_evidence_audit_log_keeps_receipts_separate_from_report(self) -> None:
        state = GuideState()
        policy_run, response_run = full_stack.make_rush_inputs()
        state.policy_analysis = policy_run
        state.response_analysis = response_run
        state.analysis = full_stack._guided_combined(policy_run, response_run)

        state.guided_begin(None)
        while state.analysis.current_step_id is not None:
            state.guided_next()

        briefed = state.brief()
        leadership = next(
            step.ai_output
            for step in briefed.steps
            if step.kind == StepKind.DRAFT_BRIEF
        )
        audit = state.evidence_audit_log()

        self.assertIn("PolicyTrace Leadership Report", leadership)
        self.assertNotIn("Exact passage:", leadership)
        self.assertIn("PolicyTrace Evidence Audit Log", audit)
        self.assertIn("Exact passage:", audit)
        self.assertIn("Evidence ID:", audit)


class NewsReportOrderingTests(unittest.TestCase):
    def test_news_is_last_supplemental_section_in_report_and_audit(self) -> None:
        guide_path = full_stack.ROOT / "backend" / "run_full_stack_guide.py"
        source = guide_path.read_text(encoding="utf-8")

        brief_block = source.split("    def brief(self)", 1)[1].split(
            "    def evidence_audit_log", 1
        )[0]
        audit_block = source.split("    def evidence_audit_log", 1)[1].split(
            "    def approve_final_brief", 1
        )[0]

        self.assertLess(
            brief_block.index("self._corpus_brief_text()"),
            brief_block.index("self._news_brief_text()"),
        )
        self.assertLess(
            audit_block.index("self._corpus_audit_text()"),
            audit_block.index("self._news_audit_text()"),
        )


class RevisionComparisonVisibilityTests(unittest.TestCase):
    def test_product_ui_exposes_authoritative_revision_comparison(self) -> None:
        index_path = full_stack.ROOT / "frontend" / "app" / "index.html"
        app_path = full_stack.ROOT / "frontend" / "app" / "app.js"
        html = index_path.read_text(encoding="utf-8")
        source = app_path.read_text(encoding="utf-8")

        self.assertIn('id="revision-doc-number"', html)
        self.assertIn('id="compare-revision"', html)
        self.assertIn('id="revision-card"', html)
        self.assertIn("Deterministic text comparison only", html)
        self.assertIn("/api/revision-compare", source)
        self.assertIn("/api/revision-comparison", source)
        self.assertIn("potentially_affected_claim_ids", source)
        self.assertIn("Shared RIN not confirmed", source)


class RevisionReviewabilityTests(unittest.TestCase):
    def test_revision_ui_filters_show_more_and_timing_are_visible(self) -> None:
        index_path = full_stack.ROOT / "frontend" / "app" / "index.html"
        app_path = full_stack.ROOT / "frontend" / "app" / "app.js"
        html = index_path.read_text(encoding="utf-8")
        source = app_path.read_text(encoding="utf-8")

        self.assertIn('data-revision-filter="substantive"', html)
        self.assertIn('data-revision-filter="threshold"', html)
        self.assertIn('id="revision-show-more"', html)
        self.assertIn("comparison_seconds", source)
        self.assertIn("from_unit_count", source)
        self.assertIn("revisionLooksLikeHeaderNoise", source)
        self.assertNotIn(".slice(0, 8)", source)


class RevisionPreviewVisibilityTests(unittest.TestCase):
    def test_comparison_is_visible_before_review_mode_starts(self) -> None:
        index_path = full_stack.ROOT / "frontend" / "app" / "index.html"
        app_path = full_stack.ROOT / "frontend" / "app" / "app.js"
        html = index_path.read_text(encoding="utf-8")
        source = app_path.read_text(encoding="utf-8")

        self.assertIn('id="review-columns"', html)
        self.assertIn('id="review-actionbar"', html)
        self.assertIn("function renderComparisonPreview()", source)
        self.assertIn(
            '!started && !revisionComparison?.available && !newsStatus?.available;',
            source,
        )
        self.assertIn('byId("review-columns").hidden = !started;', source)
        self.assertIn('byId("review-actionbar").hidden = !started;', source)
        self.assertIn("renderComparisonPreview();", source)


class FactualReportingVisibilityTests(unittest.TestCase):
    def test_phase_eight_news_discovery_is_visibly_separate(self) -> None:
        index_path = full_stack.ROOT / "frontend" / "app" / "index.html"
        app_path = full_stack.ROOT / "frontend" / "app" / "app.js"
        html = index_path.read_text(encoding="utf-8")
        source = app_path.read_text(encoding="utf-8")

        self.assertIn('id="discover-news"', html)
        self.assertIn('id="news-card"', html)
        self.assertIn("Headlines and metadata are pointers, not verified factual claims", html)
        self.assertIn("/api/news", source)
        self.assertIn("/api/news/status", source)
        self.assertIn("type-factual_reporting", source)
        self.assertIn("Open original article", source)
        self.assertNotIn("View archive history", source)
        self.assertIn('metric("coverage", "provider-specific")', source)

    def test_leadership_news_does_not_print_raw_source_urls(self) -> None:
        guide_path = full_stack.ROOT / "backend" / "run_full_stack_guide.py"
        source = guide_path.read_text(encoding="utf-8")
        news_brief = source.split("    def _news_brief_text", 1)[1].split(
            "    def _news_audit_text", 1
        )[0]
        news_audit = source.split("    def _news_audit_text", 1)[1].split(
            "    def compare_revision", 1
        )[0]

        self.assertNotIn('line += f" — {source.url}"', news_brief)
        self.assertIn('f"- URL: {source.url or \'unavailable\'}"', news_audit)

    def test_report_text_wraps_opaque_urls_for_printing(self) -> None:
        styles_path = full_stack.ROOT / "frontend" / "app" / "styles.css"
        styles = styles_path.read_text(encoding="utf-8")

        self.assertIn("overflow-wrap: anywhere", styles)
        self.assertIn("word-break: break-word", styles)
        self.assertIn("overflow-x: hidden", styles)


class MediaReviewSectionTests(unittest.TestCase):
    def test_media_is_a_real_review_section_in_guided_and_rush_modes(self) -> None:
        from datetime import datetime, timezone

        from news_sources import NewsDiscovery

        state = GuideState()
        source = full_stack.Source(
            id="source-google-news-demo",
            title="Demo policy coverage",
            information_type=full_stack.InformationType.FACTUAL_REPORTING,
            url="https://example.com/demo",
            agency="Example News",
            raw_text="Demo policy coverage",
            pii_redaction_status=full_stack.PiiRedactionStatus.NOT_APPLICABLE,
        )
        state.news_discovery = NewsDiscovery(
            query="demo policy",
            checked_at=datetime(2026, 9, 24, tzinfo=timezone.utc),
            sources=[source],
        )

        guided = state.reset("guided")
        media = next(
            step
            for step in guided.steps
            if step.kind == full_stack.StepKind.FACTUAL_REPORTING
        )
        self.assertEqual(media.id, "step-related-media")
        self.assertEqual(media.human_review.status.value, "not_reviewed")
        self.assertEqual(media.claims[0].text, "Demo policy coverage")

        rushed = state.reset("rush")
        media = next(
            step
            for step in rushed.steps
            if step.kind == full_stack.StepKind.FACTUAL_REPORTING
        )
        opened = state.rush_open(media.id)
        self.assertEqual(opened.current_step_id, "step-related-media")

    def test_reviewer_can_exclude_and_restore_media_without_a_model_call(self) -> None:
        from datetime import datetime, timezone

        from news_sources import NewsDiscovery

        state = GuideState()
        source = full_stack.Source(
            id="source-google-news-selection",
            title="Selectable article",
            information_type=full_stack.InformationType.FACTUAL_REPORTING,
            url="https://example.com/selectable",
            agency="Example News",
            raw_text="Selectable article",
            pii_redaction_status=full_stack.PiiRedactionStatus.NOT_APPLICABLE,
        )
        state.news_discovery = NewsDiscovery(
            query="selectable",
            checked_at=datetime(2026, 9, 24, tzinfo=timezone.utc),
            sources=[source],
        )
        rushed = state.reset("rush")
        media = next(
            step for step in rushed.steps
            if step.kind == full_stack.StepKind.FACTUAL_REPORTING
        )
        claim_id = media.claims[0].id

        excluded = state.set_news_article_use(claim_id, use=False)
        media = next(step for step in excluded.steps if step.id == "step-related-media")
        self.assertIn(claim_id, media.human_review.excluded_claim_ids)
        self.assertIn("Articles selected for report: 0", state._news_brief_text())
        self.assertIn("EXCLUDED BY REVIEWER", state._news_audit_text())

        restored = state.set_news_article_use(claim_id, use=True)
        media = next(step for step in restored.steps if step.id == "step-related-media")
        self.assertNotIn(claim_id, media.human_review.excluded_claim_ids)
        self.assertIn("Articles selected for report: 1", state._news_brief_text())

    def test_media_selection_survives_rush_resync(self) -> None:
        from datetime import datetime, timezone

        from news_sources import NewsDiscovery

        state = GuideState()
        source = full_stack.Source(
            id="source-google-news-persist",
            title="Persistent article",
            information_type=full_stack.InformationType.FACTUAL_REPORTING,
            url="https://example.com/persist",
            agency="Example News",
            raw_text="Persistent article",
            pii_redaction_status=full_stack.PiiRedactionStatus.NOT_APPLICABLE,
        )
        state.news_discovery = NewsDiscovery(
            query="persist",
            checked_at=datetime(2026, 9, 24, tzinfo=timezone.utc),
            sources=[source],
        )
        first = state.reset("rush")
        media = next(step for step in first.steps if step.kind == full_stack.StepKind.FACTUAL_REPORTING)
        claim_id = media.claims[0].id
        state.set_news_article_use(claim_id, use=False)

        rerun = state.reset("rush")
        media = next(step for step in rerun.steps if step.kind == full_stack.StepKind.FACTUAL_REPORTING)
        self.assertIn(claim_id, media.human_review.excluded_claim_ids)

    def test_media_step_is_excluded_from_normal_claim_promotion(self) -> None:
        selective_path = full_stack.ROOT / "backend" / "selective_reanalysis.py"
        source = selective_path.read_text(encoding="utf-8")
        self.assertIn("StepKind.FACTUAL_REPORTING", source)

    def test_product_ui_places_media_inside_section_review_flow(self) -> None:
        app_path = full_stack.ROOT / "frontend" / "app" / "app.js"
        source = app_path.read_text(encoding="utf-8")

        self.assertIn('selectedStepId = "step-related-media"', source)
        self.assertIn('step.kind === "factual_reporting"', source)
        self.assertIn("Review these discovered media/source pointers", source)
        self.assertIn('byId("news-card").hidden = true;', source)
        self.assertIn("list.hidden = Boolean(run);", source)
        self.assertIn("if (!run) {", source)


class PolicyFreshnessVisibilityTests(unittest.TestCase):
    def test_product_ui_surfaces_current_policy_status(self) -> None:
        index_path = full_stack.ROOT / "frontend" / "app" / "index.html"
        app_path = full_stack.ROOT / "frontend" / "app" / "app.js"
        html = index_path.read_text(encoding="utf-8")
        source = app_path.read_text(encoding="utf-8")

        self.assertIn('id="policy-status-card"', html)
        self.assertIn("Current status / freshness", html)
        self.assertIn("/api/source/policy/status", source)
        self.assertIn("later_material_action_found", source)
        self.assertIn("status check unavailable", source)


class CorpusLimitVisibilityTests(unittest.TestCase):
    def test_product_ui_surfaces_corpus_limits_and_precise_duplicate_wording(self) -> None:
        index_path = full_stack.ROOT / "frontend" / "app" / "index.html"
        app_path = full_stack.ROOT / "frontend" / "app" / "app.js"
        html = index_path.read_text(encoding="utf-8")
        source = app_path.read_text(encoding="utf-8")

        self.assertIn('id="corpus-card"', html)
        self.assertIn("Exact-text duplicate submissions are clustered", html)
        self.assertNotIn("duplicate form letters are not counted as separate voices", html)
        self.assertIn("/api/source/comments/status", source)
        self.assertIn("exact_text_cluster_count", source)
        self.assertIn("representativeness_warning", source)

    def test_corpus_status_uses_exact_text_clusters_not_distinct_voices(self) -> None:
        state = GuideState()
        _, response_run = full_stack.make_rush_inputs()
        source = response_run.sources[0].model_copy(deep=True)
        source.duplicate_cluster_id = "exact-text-demo"
        response_run.sources = [source]
        state.response_analysis = response_run
        state.last_comment_fetch_report = full_stack.CommentFetchReport(
            docket_id="DEMO",
            requested_count=3,
            source_document_count=1,
            observed_candidate_count=3,
            attempted_count=3,
            retrieved_count=1,
        )

        status = state.comment_corpus_status()

        self.assertTrue(status["available"])
        self.assertEqual(status["requested_count"], 3)
        self.assertEqual(status["retrieved_count"], 1)
        self.assertEqual(status["analyzed_source_count"], 1)
        self.assertEqual(status["exact_text_cluster_count"], 1)
        self.assertIn("not a representative sample", status["representativeness_warning"])

    def test_degraded_attachment_count_is_distinct_from_source_count(self) -> None:
        state = GuideState()
        _, response_run = full_stack.make_rush_inputs()
        source = response_run.sources[0]
        marker = full_stack.DEGRADED_ATTACHMENT_MARKER
        source.raw_text = (
            f"{marker} first warning]\nattachment one\n\n"
            f"{marker} second warning]\nattachment two"
        )
        response_run.sources = [source]
        state.response_analysis = response_run
        state.last_comment_fetch_report = full_stack.CommentFetchReport(
            docket_id="DEMO",
            requested_count=1,
            retrieved_count=1,
        )

        status = state.comment_corpus_status()

        self.assertEqual(status["degraded_source_count"], 1)
        self.assertEqual(status["degraded_attachment_count"], 2)

    def test_final_brief_includes_corpus_limits_when_comments_are_present(self) -> None:
        state = GuideState()
        policy_run, response_run = full_stack.make_rush_inputs()
        state.policy_analysis = policy_run
        state.response_analysis = response_run
        state.analysis = full_stack._guided_combined(policy_run, response_run)
        state.last_comment_fetch_report = full_stack.CommentFetchReport(
            docket_id="DEMO",
            requested_count=2,
            source_document_count=1,
            observed_candidate_count=2,
            attempted_count=2,
            retrieved_count=1,
            failures=[
                CommentFetchFailure(
                    comment_id="COMMENT-2",
                    error_type="TimeoutError",
                )
            ],
        )

        state.guided_begin(None)
        while state.analysis.current_step_id is not None:
            state.guided_next()

        briefed = state.brief()
        brief = next(step for step in briefed.steps if step.kind.value == "draft_brief")

        self.assertIn("## Corpus limits", brief.ai_output)
        self.assertIn("Retrieval failures: 1", brief.ai_output)
        self.assertIn("Exact-text clusters:", brief.ai_output)
        self.assertIn("not a representative sample", brief.ai_output)

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

    def test_failed_provider_save_does_not_destroy_working_credentials(self) -> None:
        state = GuideState()
        state.provider.configure(
            {
                "kind": "openrouter",
                "api_key": "working-key",
                "regulations_api_key": "regs-key",
            }
        )

        with self.assertRaisesRegex(ValueError, "API key is required"):
            state.provider.configure(
                {
                    "kind": "openrouter",
                    "api_key": "",
                    "regulations_api_key": "regs-key",
                }
            )

        self.assertEqual(state.provider.kind, "openrouter")
        self.assertEqual(state.provider.api_key, "working-key")
        self.assertEqual(state.provider.regulations_api_key, "regs-key")


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


class RushStartAndFlagFeedbackTests(unittest.TestCase):
    def test_rush_can_open_first_human_section_immediately(self) -> None:
        state = GuideState()
        rushed = state.reset("rush")
        first = next(
            step for step in rushed.steps
            if step.kind.value not in {"verification", "draft_brief"}
        )
        opened = state.rush_open(first.id)
        self.assertEqual(opened.mode, AnalysisMode.RUSH)
        self.assertEqual(opened.current_step_id, first.id)
        self.assertEqual(
            next(step for step in opened.steps if step.id == first.id).human_review.status,
            HumanReviewStatus.IN_REVIEW,
        )

    def test_flag_is_persisted_on_the_claim(self) -> None:
        state = GuideState()
        rushed = state.reset("rush")
        first = next(
            step for step in rushed.steps
            if step.kind.value not in {"verification", "draft_brief"}
        )
        state.rush_open(first.id)
        claim_id = first.claims[0].id
        flagged = state.guided_flag(claim_id, "Reviewer found a problem")
        updated = next(step for step in flagged.steps if step.id == first.id)
        self.assertIn(claim_id, updated.human_review.flagged_claim_ids)
        self.assertTrue(
            any("Reviewer found a problem" in note for note in updated.human_review.notes)
        )


class ReviewerFlagGateTests(unittest.TestCase):
    def _review_all_guided(self, state: GuideState) -> None:
        state.guided_begin(None)
        while state.analysis.current_step_id is not None:
            state.guided_next()

    def test_flag_requires_a_reason(self) -> None:
        state = GuideState()
        state.reset("guided")
        begun = state.guided_begin(None)
        claim_id = begun.steps[0].claims[0].id

        with self.assertRaisesRegex(ValueError, "flag reason"):
            state.guided_flag(claim_id, "   ")

    def test_guided_edit_resolves_existing_flag(self) -> None:
        state = GuideState()
        state.reset("guided")
        begun = state.guided_begin(None)
        claim_id = begun.steps[0].claims[0].id

        state.guided_flag(claim_id, "The affected group is overstated.")
        edited = state.guided_edit(claim_id, "Reviewer corrected the affected group.")

        step = edited.steps[0]
        self.assertNotIn(claim_id, step.human_review.flagged_claim_ids)
        self.assertTrue(
            any(
                f"Resolved flag {claim_id}" in note
                for note in step.human_review.notes
            )
        )

    def test_flag_survives_review_and_is_preserved_in_audit_log(self) -> None:
        state = GuideState()
        state.reset("guided")
        begun = state.guided_begin(None)
        claim_id = begun.steps[0].claims[0].id

        state.guided_flag(
            claim_id,
            'The source says "covered", not "licensed".',
        )
        self._review_all_guided(state)
        briefed = state.brief()
        brief = next(step for step in briefed.steps if step.kind.value == "draft_brief")
        audit = state.evidence_audit_log()

        self.assertNotIn(
            'FLAGGED BY REVIEWER: The source says "covered", not "licensed".',
            brief.ai_output,
        )
        self.assertIn(
            'FLAGGED BY REVIEWER: The source says "covered", not "licensed".',
            audit,
        )
        self.assertIn("Report promotion: BLOCKED", audit)

        with self.assertRaisesRegex(ValueError, "reviewer flags"):
            state.approve_final_brief()

        approved = state.approve_final_brief(acknowledge_flags=True)
        self.assertEqual(approved.final_review_status, HumanReviewStatus.APPROVED)
        flagged_step = approved.steps[0]
        self.assertTrue(
            any(
                "acknowledged unresolved reviewer flag" in note
                for note in flagged_step.human_review.notes
            )
        )

    def test_rush_human_edit_resolves_flag(self) -> None:
        state = GuideState()
        rushed = state.reset("rush")
        step = next(item for item in rushed.steps if item.claims)
        state.rush_open(step.id)
        claim_id = step.claims[0].id
        state.guided_flag(claim_id, "Reviewer disputes this wording.")

        edited = state.reanalyze(
            step.id,
            "Reviewer replacement wording.",
            claim_id=claim_id,
            human_edited=True,
        )
        updated = next(item for item in edited.steps if item.id == step.id)
        self.assertNotIn(claim_id, updated.human_review.flagged_claim_ids)
        self.assertTrue(
            any(
                f"Resolved flag {claim_id}" in note
                for note in updated.human_review.notes
            )
        )


class ErrorLogTests(unittest.TestCase):
    def test_error_log_persists_safe_metadata_and_redacts_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "errors.jsonl"
            with (
                patch.object(full_stack, "ERROR_LOG_PATH", path),
                patch.object(
                    full_stack.STATE.provider,
                    "api_key",
                    "super-secret-api-key",
                ),
            ):
                error_id, safe = full_stack._record_error(
                    method="POST",
                    path="/api/provider",
                    status=400,
                    message="provider rejected super-secret-api-key",
                    error_type="ValueError",
                )
                recent = full_stack._recent_errors()

            self.assertTrue(error_id.startswith("ERR-"))
            self.assertNotIn("super-secret-api-key", safe)
            self.assertEqual(len(recent), 1)
            self.assertEqual(recent[0]["error_id"], error_id)
            self.assertEqual(recent[0]["path"], "/api/provider")
            self.assertEqual(recent[0]["status"], 400)
            self.assertNotIn("super-secret-api-key", json.dumps(recent))
            self.assertNotIn("request_body", recent[0])

    def test_recent_errors_survive_multiple_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "errors.jsonl"
            with patch.object(full_stack, "ERROR_LOG_PATH", path):
                first, _ = full_stack._record_error(
                    method="POST",
                    path="/api/one",
                    status=400,
                    message="first",
                    error_type="ValueError",
                )
                second, _ = full_stack._record_error(
                    method="POST",
                    path="/api/two",
                    status=502,
                    message="second",
                    error_type="RuntimeError",
                )
                recent = full_stack._recent_errors(limit=2)

            self.assertEqual(
                [entry["error_id"] for entry in recent],
                [first, second],
            )


class HiddenVerificationRefreshRegressionTests(unittest.TestCase):
    def test_hidden_verification_refresh_does_not_block_final_brief(self) -> None:
        state = GuideState()
        rushed = state.reset("rush")

        content = [
            step
            for step in rushed.steps
            if step.kind.value not in {"verification", "draft_brief"}
        ]
        first = content[0]

        state.rush_open(first.id)
        edited = state.reanalyze(
            first.id,
            "Reviewer correction.",
            claim_id=first.claims[0].id,
            human_edited=True,
        )

        verification = next(
            step for step in edited.steps if step.kind.value == "verification"
        )
        self.assertEqual(verification.status, StepStatus.NEEDS_REFRESH)

        # Refresh and review every user-facing stale/content section only.
        while True:
            stale_content = next(
                (
                    step
                    for step in state.analysis.steps
                    if step.kind.value not in {"verification", "draft_brief"}
                    and step.status == StepStatus.NEEDS_REFRESH
                    and all(
                        next(
                            dep
                            for dep in state.analysis.steps
                            if dep.id == dependency
                        ).status != StepStatus.NEEDS_REFRESH
                        for dependency in step.depends_on
                    )
                ),
                None,
            )
            if stale_content is None:
                break
            state.refresh(stale_content.id)

        for step in [
            item
            for item in state.analysis.steps
            if item.kind.value not in {"verification", "draft_brief"}
        ]:
            state.review_reanalysis(step.id)

        # The internal verification summary can remain stale; it is not a
        # human-facing brief dependency and must not trap the reviewer.
        verification = next(
            step for step in state.analysis.steps if step.kind.value == "verification"
        )
        self.assertEqual(verification.status, StepStatus.NEEDS_REFRESH)

        briefed = state.brief()
        self.assertTrue(
            any(step.kind.value == "draft_brief" for step in briefed.steps)
        )


class PolicyIntakeUiContractTests(unittest.TestCase):
    def test_phase_nine_source_builder_is_the_primary_start_flow(self) -> None:
        index_path = full_stack.ROOT / "frontend" / "app" / "index.html"
        app_path = full_stack.ROOT / "frontend" / "app" / "app.js"
        html = index_path.read_text(encoding="utf-8")
        source = app_path.read_text(encoding="utf-8")

        self.assertIn("Policy Intake / Source Builder", html)
        self.assertIn('id="policy-search-query"', html)
        self.assertIn('id="policy-search-results"', html)
        self.assertIn('id="include-comments"', html)
        self.assertIn('id="comment-sampling-method"', html)
        self.assertIn('id="comment-sampling-seed"', html)
        self.assertIn('id="include-news"', html)
        self.assertIn('id="include-comparison"', html)
        self.assertIn('id="report-standard"', html)
        self.assertIn('id="save-project"', html)
        self.assertIn('id="load-project"', html)
        self.assertIn('id="save-project-final"', html)
        self.assertIn('id="start-rush"', html)

        self.assertIn('api("/api/intake/search"', source)
        self.assertIn('api("/api/intake/select"', source)
        self.assertIn('api("/api/intake/workload"', source)
        self.assertIn('api("/api/intake/run"', source)
        self.assertIn("policytrace_project_schema: 1", source)
        self.assertIn("comment_sampling_method", source)
        self.assertIn("comment_sampling_seed", source)
        self.assertIn("ensureCommentSamplingSeed", source)
        self.assertIn('byId("save-project-final").addEventListener', source)

    def test_random_comment_sampling_is_visible_and_keeps_representativeness_warning(self) -> None:
        index_path = full_stack.ROOT / "frontend" / "app" / "index.html"
        app_path = full_stack.ROOT / "frontend" / "app" / "app.js"
        html = index_path.read_text(encoding="utf-8")
        source = app_path.read_text(encoding="utf-8")

        self.assertIn("Random — reproducible spread", html)
        self.assertIn("does not make regulatory comments representative", html)
        self.assertIn("sampling_method === \"random\"", source)
        self.assertIn("selected_positions", source)

    def test_docket_autofill_requires_explicit_regulations_pointer(self) -> None:
        index_path = full_stack.ROOT / "frontend" / "app" / "index.html"
        app_path = full_stack.ROOT / "frontend" / "app" / "app.js"
        html = index_path.read_text(encoding="utf-8")
        source = app_path.read_text(encoding="utf-8")

        self.assertIn('id="docket-detection-note"', html)
        self.assertIn('id="include-notices-search"', html)
        self.assertIn("docket_detection", source)
        self.assertNotIn(
            "const dockets = intakeState?.document?.docket_ids || []",
            source,
        )
        self.assertIn("detection.status === \"single\"", source)
        self.assertIn("include_notices:", source)

    def test_intake_discloses_optional_source_failures_without_stopping(self) -> None:
        app_path = full_stack.ROOT / "frontend" / "app" / "app.js"
        source = app_path.read_text(encoding="utf-8")

        self.assertIn('api("/api/intake/current")', source)
        self.assertIn("source acquisition warning", source)

    def test_large_comparison_has_two_level_guardrail(self) -> None:
        app_path = full_stack.ROOT / "frontend" / "app" / "app.js"
        source = app_path.read_text(encoding="utf-8")

        self.assertIn("workload.confirmation_steps >= 1", source)
        self.assertIn("workload.confirmation_steps >= 2", source)
        self.assertIn("Large comparison:", source)
        self.assertIn("Confirm very large analysis:", source)

    def test_project_file_never_collects_credentials(self) -> None:
        app_path = full_stack.ROOT / "frontend" / "app" / "app.js"
        source = app_path.read_text(encoding="utf-8")
        project_block = source.split("function projectPayload()", 1)[1].split(
            "function saveProjectFile", 1
        )[0]

        self.assertNotIn("provider-key", project_block)
        self.assertNotIn("provider-bearer", project_block)
        self.assertNotIn("regs-key", project_block)
        self.assertNotIn("mediacloud-key", project_block)


class LiveSourceModeChoiceContractTests(unittest.TestCase):
    def test_live_source_ui_exposes_rush_as_the_single_user_start_path(self) -> None:
        app_path = full_stack.ROOT / "frontend" / "app" / "app.js"
        index_path = full_stack.ROOT / "frontend" / "app" / "index.html"
        source = app_path.read_text(encoding="utf-8")
        html = index_path.read_text(encoding="utf-8")

        self.assertNotIn('id="start-guided"', html)
        self.assertIn('id="start-rush"', html)
        self.assertIn("Analyze everything, then review", html)
        self.assertNotIn('byId("start-guided")', source)
        self.assertIn('byId("mode-pill").textContent = "ready to analyze"', source)
        self.assertIn(
            "Live comments analyzed. Corpus limits are tracked for review.",
            source,
        )

    def test_frontend_has_one_write_request_at_a_time_guard(self) -> None:
        app_path = full_stack.ROOT / "frontend" / "app" / "app.js"
        source = app_path.read_text(encoding="utf-8")

        self.assertIn("apiRequestInFlight", source)
        self.assertIn("still working on the previous request", source)
