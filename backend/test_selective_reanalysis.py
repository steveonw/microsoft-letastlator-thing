import unittest
from datetime import datetime, timezone

from models import (
    AnalysisMode,
    AnalysisRun,
    AnalysisStep,
    Claim,
    Evidence,
    HumanReview,
    HumanReviewStatus,
    InformationType,
    PiiRedactionStatus,
    Policy,
    ReportStandard,
    Source,
    StepKind,
    StepStatus,
    VerificationStatus,
)
from selective_reanalysis import (
    ReanalysisResult,
    build_evidence_audit_log,
    build_final_brief,
    dependent_step_ids,
    reanalyze_step,
    refresh_step,
)


RAW_TEXT = (
    "Section one creates a reporting duty. "
    "Section two identifies covered providers. "
    "Section three sets a filing deadline."
)


def claim(claim_id: str, text: str, evidence_id: str) -> Claim:
    return Claim(
        id=claim_id,
        text=text,
        information_type=InformationType.AI_INTERPRETATION,
        evidence_ids=[evidence_id],
        verification_status=VerificationStatus.SUPPORTED,
        confidence="high",
    )


def demo_analysis() -> AnalysisRun:
    source = Source(
        id="source-policy",
        title="Demo policy",
        information_type=InformationType.OFFICIAL_POLICY,
        raw_text=RAW_TEXT,
        pii_redaction_status=PiiRedactionStatus.NOT_APPLICABLE,
    )
    evidence_one = Evidence(
        id="evidence-one",
        source_id=source.id,
        snippet="Section one creates a reporting duty.",
        start_offset=0,
        end_offset=len("Section one creates a reporting duty."),
        retrieved_at=datetime(2026, 9, 23, tzinfo=timezone.utc),
    )
    start_two = RAW_TEXT.index("Section two")
    evidence_two = Evidence(
        id="evidence-two",
        source_id=source.id,
        snippet="Section two identifies covered providers.",
        start_offset=start_two,
        end_offset=start_two + len("Section two identifies covered providers."),
        retrieved_at=datetime(2026, 9, 23, tzinfo=timezone.utc),
    )
    start_three = RAW_TEXT.index("Section three")
    evidence_three = Evidence(
        id="evidence-three",
        source_id=source.id,
        snippet="Section three sets a filing deadline.",
        start_offset=start_three,
        end_offset=start_three + len("Section three sets a filing deadline."),
        retrieved_at=datetime(2026, 9, 23, tzinfo=timezone.utc),
    )

    step_one = AnalysisStep(
        id="step-one",
        kind=StepKind.POLICY_UNDERSTANDING,
        title="Understand policy",
        status=StepStatus.VERIFIED,
        claims=[claim("claim-one", "The policy creates a reporting duty.", "evidence-one")],
        human_review=HumanReview(status=HumanReviewStatus.REVIEWED),
        version=1,
    )
    step_two = AnalysisStep(
        id="step-two",
        kind=StepKind.MAJOR_PROVISIONS,
        title="Major provisions",
        status=StepStatus.VERIFIED,
        depends_on=[step_one.id],
        claims=[claim("claim-two", "Covered providers are identified.", "evidence-two")],
        human_review=HumanReview(status=HumanReviewStatus.REVIEWED),
        version=2,
    )
    sibling = AnalysisStep(
        id="step-sibling",
        kind=StepKind.AFFECTED_PROGRAMS,
        title="Affected programs",
        status=StepStatus.VERIFIED,
        depends_on=[step_one.id],
        claims=[claim("claim-sibling", "A separate reviewed finding remains stable.", "evidence-one")],
        human_review=HumanReview(status=HumanReviewStatus.REVIEWED),
        version=4,
    )
    step_three = AnalysisStep(
        id="step-three",
        kind=StepKind.STAKEHOLDERS,
        title="Stakeholders",
        status=StepStatus.VERIFIED,
        depends_on=[step_two.id],
        claims=[claim("claim-three", "Covered providers are directly affected.", "evidence-two")],
        human_review=HumanReview(status=HumanReviewStatus.REVIEWED),
        version=1,
    )
    step_four = AnalysisStep(
        id="step-four",
        kind=StepKind.PUBLIC_RESPONSE,
        title="Public response",
        status=StepStatus.VERIFIED,
        depends_on=[step_three.id],
        claims=[claim("claim-four", "The filing deadline is part of the analyzed material.", "evidence-three")],
        human_review=HumanReview(status=HumanReviewStatus.REVIEWED),
        version=1,
    )

    return AnalysisRun(
        id="run-chunk9-demo",
        mode=AnalysisMode.GUIDED,
        policy=Policy(
            id="policy-demo",
            title="Demo policy",
            jurisdiction="United States / federal",
            source_ids=[source.id],
        ),
        sources=[source],
        evidence=[evidence_one, evidence_two, evidence_three],
        steps=[step_one, step_two, sibling, step_three, step_four],
        current_step_id=step_four.id,
        final_review_status=HumanReviewStatus.APPROVED,
    )


class SelectiveReanalysisTests(unittest.TestCase):
    def test_dependency_walk_returns_only_transitive_descendants(self) -> None:
        analysis = demo_analysis()

        self.assertEqual(
            dependent_step_ids(analysis, "step-two"),
            ["step-three", "step-four"],
        )

    def test_reanalysis_changes_selected_step_and_invalidates_only_descendants(self) -> None:
        analysis = demo_analysis()
        sibling_before = analysis.steps[2].model_dump(mode="python")
        upstream_before = analysis.steps[0].model_dump(mode="python")

        def reanalyzer(snapshot: AnalysisRun, selected: AnalysisStep) -> ReanalysisResult:
            self.assertEqual(snapshot.id, analysis.id)
            replacement = selected.model_copy(deep=True)
            replacement.claims[0].text = "Covered providers are explicitly identified."
            return ReanalysisResult(step=replacement)

        updated = reanalyze_step(analysis, "step-two", reanalyzer)

        self.assertEqual(updated.current_step_id, "step-two")
        self.assertEqual(updated.steps[1].version, 3)
        self.assertEqual(updated.steps[1].status, StepStatus.DRAFT)
        self.assertEqual(
            updated.steps[1].human_review.status,
            HumanReviewStatus.IN_REVIEW,
        )
        self.assertEqual(
            updated.steps[1].claims[0].text,
            "Covered providers are explicitly identified.",
        )
        self.assertEqual(updated.steps[3].status, StepStatus.NEEDS_REFRESH)
        self.assertEqual(updated.steps[4].status, StepStatus.NEEDS_REFRESH)
        self.assertEqual(
            updated.steps[3].human_review.status,
            HumanReviewStatus.NOT_REVIEWED,
        )
        self.assertEqual(
            updated.steps[4].human_review.status,
            HumanReviewStatus.NOT_REVIEWED,
        )
        self.assertEqual(
            updated.steps[2].model_dump(mode="python"),
            sibling_before,
        )
        self.assertEqual(
            updated.steps[0].model_dump(mode="python"),
            upstream_before,
        )
        self.assertEqual(
            updated.final_review_status,
            HumanReviewStatus.NOT_REVIEWED,
        )

    def test_reanalysis_requires_identity_and_dependencies_to_stay_stable(self) -> None:
        analysis = demo_analysis()

        def wrong_id(snapshot: AnalysisRun, selected: AnalysisStep) -> ReanalysisResult:
            del snapshot
            replacement = selected.model_copy(deep=True)
            replacement.id = "replacement-step"
            return ReanalysisResult(step=replacement)

        with self.assertRaisesRegex(ValueError, "preserve the selected step ID"):
            reanalyze_step(analysis, "step-two", wrong_id)

        def wrong_dependencies(
            snapshot: AnalysisRun,
            selected: AnalysisStep,
        ) -> ReanalysisResult:
            del snapshot
            replacement = selected.model_copy(deep=True)
            replacement.depends_on = []
            return ReanalysisResult(step=replacement)

        with self.assertRaisesRegex(ValueError, "preserve .* dependencies"):
            reanalyze_step(analysis, "step-two", wrong_dependencies)

    def test_refresh_enforces_dependency_order_and_leaves_other_stale_steps_alone(self) -> None:
        analysis = demo_analysis()

        def revise(snapshot: AnalysisRun, selected: AnalysisStep) -> ReanalysisResult:
            del snapshot
            replacement = selected.model_copy(deep=True)
            replacement.claims[0].text += " Updated."
            return ReanalysisResult(step=replacement)

        changed = reanalyze_step(analysis, "step-two", revise)

        with self.assertRaisesRegex(ValueError, "cannot refresh before dependencies"):
            refresh_step(changed, "step-four", revise)

        refreshed_three = refresh_step(changed, "step-three", revise)
        self.assertEqual(refreshed_three.steps[3].status, StepStatus.DRAFT)
        self.assertEqual(refreshed_three.steps[4].status, StepStatus.NEEDS_REFRESH)

        refreshed_four = refresh_step(refreshed_three, "step-four", revise)
        self.assertEqual(refreshed_four.steps[4].status, StepStatus.DRAFT)
        self.assertNotIn(
            StepStatus.NEEDS_REFRESH,
            [step.status for step in refreshed_four.steps],
        )

    def test_reanalysis_can_add_new_evidence_without_overwriting_existing_evidence(self) -> None:
        analysis = demo_analysis()
        start = RAW_TEXT.index("Section three")
        new_evidence = Evidence(
            id="evidence-new",
            source_id="source-policy",
            snippet="Section three sets a filing deadline.",
            start_offset=start,
            end_offset=start + len("Section three sets a filing deadline."),
            retrieved_at=datetime(2026, 9, 23, tzinfo=timezone.utc),
        )

        def reanalyzer(snapshot: AnalysisRun, selected: AnalysisStep) -> ReanalysisResult:
            del snapshot
            replacement = selected.model_copy(deep=True)
            replacement.claims[0].evidence_ids = [new_evidence.id]
            return ReanalysisResult(step=replacement, evidence=(new_evidence,))

        updated = reanalyze_step(analysis, "step-two", reanalyzer)

        self.assertIn("evidence-new", {item.id for item in updated.evidence})
        self.assertEqual(
            updated.steps[1].claims[0].evidence_ids,
            ["evidence-new"],
        )
        self.assertEqual(len(analysis.evidence), 3)

    def test_final_brief_refuses_stale_graph(self) -> None:
        analysis = demo_analysis()

        def revise(snapshot: AnalysisRun, selected: AnalysisStep) -> ReanalysisResult:
            del snapshot
            return ReanalysisResult(step=selected)

        stale = reanalyze_step(analysis, "step-two", revise)

        with self.assertRaisesRegex(ValueError, "steps need refresh"):
            build_final_brief(stale)

    def test_final_brief_copies_reviewed_claims_and_traceability_exactly(self) -> None:
        analysis = demo_analysis()
        analysis.final_review_status = HumanReviewStatus.NOT_REVIEWED
        analysis.steps[4].human_review.status = HumanReviewStatus.NOT_REVIEWED

        briefed = build_final_brief(analysis)
        brief = briefed.steps[-1]

        self.assertEqual(brief.kind, StepKind.DRAFT_BRIEF)
        self.assertEqual(brief.id, "step-draft-brief")
        self.assertEqual(
            brief.human_review.status,
            HumanReviewStatus.IN_REVIEW,
        )
        self.assertEqual(
            briefed.final_review_status,
            HumanReviewStatus.IN_REVIEW,
        )
        self.assertIn(
            "The policy creates a reporting duty. [claim-one]",
            brief.ai_output,
        )
        self.assertNotIn("Exact passage:", brief.ai_output)
        self.assertIn(
            "Covered providers are identified. [claim-two]",
            brief.ai_output,
        )
        self.assertIn(
            "A separate reviewed finding remains stable. [claim-sibling]",
            brief.ai_output,
        )
        self.assertNotIn("[claim-four]", brief.ai_output)
        self.assertEqual(brief.claims, [])

    def test_zero_evidence_ai_claim_is_kept_audit_only(self) -> None:
        analysis = demo_analysis()
        claim = analysis.steps[0].claims[0]
        claim.evidence_ids = []
        claim.verification_status = VerificationStatus.NEEDS_HUMAN_REVIEW
        claim.verification_note = "No cited evidence is available."

        briefed = build_final_brief(analysis)
        leadership = briefed.steps[-1].ai_output
        audit = build_evidence_audit_log(briefed)

        self.assertNotIn("[claim-one]", leadership)
        self.assertIn("1 reviewed finding(s) were withheld", leadership)
        self.assertIn("Claim ID: claim-one", audit)
        self.assertIn("Report promotion: BLOCKED", audit)
        self.assertIn("No cited evidence", audit)

    def test_unresolved_verification_is_not_promoted_even_with_evidence(self) -> None:
        analysis = demo_analysis()
        claim = analysis.steps[1].claims[0]
        claim.verification_status = VerificationStatus.NEEDS_HUMAN_REVIEW
        claim.verification_note = "Semantic support requires human review."

        briefed = build_final_brief(analysis)
        leadership = briefed.steps[-1].ai_output
        audit = build_evidence_audit_log(briefed)

        self.assertNotIn("[claim-two]", leadership)
        self.assertIn("Claim ID: claim-two", audit)
        self.assertIn("needs_human_review", audit)

    def test_reviewer_flag_blocks_normal_report_promotion(self) -> None:
        analysis = demo_analysis()
        step = analysis.steps[0]
        step.human_review.flagged_claim_ids.append("claim-one")
        step.human_review.notes.append("Flagged claim-one: Reviewer disputes this wording.")

        briefed = build_final_brief(analysis)
        leadership = briefed.steps[-1].ai_output
        audit = build_evidence_audit_log(briefed)

        self.assertNotIn("[claim-one]", leadership)
        self.assertIn("Claim ID: claim-one", audit)
        self.assertIn("Reviewer flag remains unresolved", audit)
        self.assertIn("FLAGGED BY REVIEWER", audit)

    def test_audit_log_contains_exact_evidence_receipts_and_source_metadata(self) -> None:
        analysis = demo_analysis()

        audit = build_evidence_audit_log(analysis)

        self.assertIn("PolicyTrace Evidence Audit Log", audit)
        self.assertIn("Claim ID: claim-one", audit)
        self.assertIn("Evidence ID: evidence-one", audit)
        self.assertIn("Source title: Demo policy", audit)
        self.assertIn("Source type: official_policy", audit)
        self.assertIn("Exact passage:", audit)
        self.assertIn("Section one creates a reporting duty.", audit)

    def test_leadership_report_uses_stable_claim_ids_without_evidence_dump(self) -> None:
        analysis = demo_analysis()

        briefed = build_final_brief(analysis)
        report = briefed.steps[-1].ai_output

        self.assertIn("PolicyTrace Leadership Report", report)
        self.assertIn("[claim-one]", report)
        self.assertNotIn("Evidence ID:", report)
        self.assertNotIn("Exact passage:", report)

    def test_final_approval_can_supply_acceptance_for_rush_sections(self) -> None:
        analysis = demo_analysis()
        analysis.mode = AnalysisMode.RUSH
        for step in analysis.steps:
            step.human_review.status = HumanReviewStatus.NOT_REVIEWED
        analysis.final_review_status = HumanReviewStatus.APPROVED

        briefed = build_final_brief(analysis)
        brief = briefed.steps[-1]

        self.assertIn("[claim-one]", brief.ai_output)
        self.assertIn("[claim-four]", brief.ai_output)



class ReportStandardTests(unittest.TestCase):
    def test_strict_withholds_partially_supported_findings(self) -> None:
        analysis = demo_analysis()
        claim = analysis.steps[1].claims[0]
        claim.verification_status = VerificationStatus.PARTIALLY_SUPPORTED
        claim.verification_note = "Only part of this finding is established."
        analysis.report_standard = ReportStandard.STRICT

        briefed = build_final_brief(analysis)
        brief = next(step for step in briefed.steps if step.kind == StepKind.DRAFT_BRIEF)

        self.assertIn("Report standard: strict", brief.ai_output)
        self.assertNotIn("Covered providers are identified.", brief.ai_output)

    def test_balanced_keeps_partially_supported_findings_labeled(self) -> None:
        analysis = demo_analysis()
        claim = analysis.steps[1].claims[0]
        claim.verification_status = VerificationStatus.PARTIALLY_SUPPORTED
        claim.verification_note = "Only part of this finding is established."
        analysis.report_standard = ReportStandard.BALANCED

        briefed = build_final_brief(analysis)
        brief = next(step for step in briefed.steps if step.kind == StepKind.DRAFT_BRIEF)

        self.assertIn("Covered providers are identified.", brief.ai_output)
        self.assertIn("(partially supported)", brief.ai_output)

    def test_exploratory_surfaces_unresolved_evidence_separately(self) -> None:
        analysis = demo_analysis()
        claim = analysis.steps[1].claims[0]
        claim.verification_status = VerificationStatus.NEEDS_HUMAN_REVIEW
        claim.verification_note = "Evidence exists but semantic support is unresolved."
        analysis.report_standard = ReportStandard.EXPLORATORY

        briefed = build_final_brief(analysis)
        brief = next(step for step in briefed.steps if step.kind == StepKind.DRAFT_BRIEF)

        self.assertIn("## Exploratory reviewed findings", brief.ai_output)
        self.assertIn("[needs_human_review]", brief.ai_output)
        self.assertIn("not established findings", brief.ai_output)


if __name__ == "__main__":
    unittest.main()


class ReanalysisEditTrailTests(unittest.TestCase):
    """
    Guided mode records human edits. Re-analysis has to record them too, or the
    same edit is audited in one mode and anonymous in the other.
    """

    def _human_edit(self, run: AnalysisRun, step_id: str, text: str) -> AnalysisRun:
        def regenerate(
            snapshot: AnalysisRun, selected: AnalysisStep
        ) -> ReanalysisResult:
            del snapshot
            replacement = selected.model_copy(deep=True)
            replacement.claims[0].text = text
            return ReanalysisResult(
                step=replacement,
                human_edited_claim_ids=(replacement.claims[0].id,),
            )

        return reanalyze_step(run, step_id, regenerate)

    def test_human_edit_keeps_original_wording_and_retypes_claim(self) -> None:
        run = demo_analysis()
        step_id = run.steps[0].id
        before = run.steps[0].claims[0].text

        updated = self._human_edit(run, step_id, "Human rewording of the finding.")
        claim = updated.steps[0].claims[0]

        self.assertEqual(claim.text, "Human rewording of the finding.")
        self.assertEqual(claim.original_text, before)
        self.assertEqual(claim.information_type, InformationType.HUMAN_INTERPRETATION)
        self.assertIn(claim.id, updated.steps[0].human_review.edited_claim_ids)

    def test_machine_regeneration_is_not_marked_human(self) -> None:
        run = demo_analysis()
        step_id = run.steps[0].id

        def regenerate(
            snapshot: AnalysisRun, selected: AnalysisStep
        ) -> ReanalysisResult:
            del snapshot
            replacement = selected.model_copy(deep=True)
            replacement.claims[0].text = "Model regenerated this finding."
            return ReanalysisResult(step=replacement)

        updated = reanalyze_step(run, step_id, regenerate)
        claim = updated.steps[0].claims[0]

        self.assertEqual(claim.information_type, InformationType.AI_INTERPRETATION)
        self.assertIsNone(claim.original_text)
        self.assertEqual(updated.steps[0].human_review.edited_claim_ids, [])

    def test_unknown_human_edited_claim_is_rejected(self) -> None:
        run = demo_analysis()

        def regenerate(
            snapshot: AnalysisRun, selected: AnalysisStep
        ) -> ReanalysisResult:
            del snapshot
            return ReanalysisResult(
                step=selected.model_copy(deep=True),
                human_edited_claim_ids=("claim-does-not-exist",),
            )

        with self.assertRaises(ValueError):
            reanalyze_step(run, run.steps[0].id, regenerate)
