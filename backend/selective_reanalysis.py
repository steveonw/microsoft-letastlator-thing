from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field

from models import (
    AnalysisRun,
    AnalysisStep,
    Evidence,
    HumanReview,
    HumanReviewStatus,
    InformationType,
    StepKind,
    VerificationStatus,
    StepStatus,
)


@dataclass(frozen=True)
class ReanalysisResult:
    """One regenerated step plus any new evidence it created."""

    step: AnalysisStep
    evidence: tuple[Evidence, ...] = field(default_factory=tuple)
    human_edited_claim_ids: tuple[str, ...] = field(default_factory=tuple)
    """
    Claims in `step` whose wording a human wrote, not the model.

    Listed IDs keep their pre-edit wording in `original_text`, are retyped as
    human_interpretation, and are recorded in the step's edited_claim_ids so the
    final brief can show exactly which words a person changed. Leave this empty
    for machine regeneration: an AI rewrite is still ai_interpretation.
    """


StepReanalyzer = Callable[[AnalysisRun, AnalysisStep], ReanalysisResult]


def _validated_copy(analysis: AnalysisRun) -> AnalysisRun:
    return AnalysisRun.model_validate(analysis.model_dump(mode="python"))


def _step_index(analysis: AnalysisRun, step_id: str) -> int:
    for index, step in enumerate(analysis.steps):
        if step.id == step_id:
            return index
    raise ValueError(f"unknown analysis step {step_id!r}")


def dependent_step_ids(analysis: AnalysisRun, step_id: str) -> list[str]:
    """Return transitive dependents in the AnalysisRun's stable step order."""
    _step_index(analysis, step_id)

    dependents: dict[str, list[str]] = {step.id: [] for step in analysis.steps}
    for step in analysis.steps:
        for dependency in step.depends_on:
            dependents[dependency].append(step.id)

    discovered: set[str] = set()
    queue = deque(dependents[step_id])
    while queue:
        candidate = queue.popleft()
        if candidate in discovered:
            continue
        discovered.add(candidate)
        queue.extend(dependents[candidate])

    return [step.id for step in analysis.steps if step.id in discovered]


def mark_dependent_steps_needs_refresh(
    analysis: AnalysisRun,
    changed_step_id: str,
) -> AnalysisRun:
    """
    Invalidate only transitive descendants of a changed step.

    The changed step itself is left untouched. Any prior final approval is revoked
    because the saved report no longer represents one fully reviewed dependency graph.
    """
    updated = _validated_copy(analysis)
    dependent_ids = set(dependent_step_ids(updated, changed_step_id))

    for step in updated.steps:
        if step.id not in dependent_ids:
            continue
        step.status = StepStatus.NEEDS_REFRESH
        step.human_review.status = HumanReviewStatus.NOT_REVIEWED

    updated.final_review_status = HumanReviewStatus.NOT_REVIEWED
    return _validated_copy(updated)


def _merge_reanalysis_evidence(
    analysis: AnalysisRun,
    items: tuple[Evidence, ...],
) -> None:
    evidence_by_id = {item.id: item for item in analysis.evidence}
    source_ids = {source.id for source in analysis.sources}

    for item in items:
        if item.source_id not in source_ids:
            raise ValueError(
                f"re-analysis evidence {item.id!r} references unknown source "
                f"{item.source_id!r}"
            )

        existing = evidence_by_id.get(item.id)
        if existing is not None:
            if existing.model_dump(mode="python") != item.model_dump(mode="python"):
                raise ValueError(
                    f"re-analysis evidence conflicts with existing ID {item.id!r}"
                )
            continue

        copied = item.model_copy(deep=True)
        analysis.evidence.append(copied)
        evidence_by_id[copied.id] = copied


def _record_human_edits(
    original: AnalysisStep,
    replacement: AnalysisStep,
    human_edited_claim_ids: tuple[str, ...],
) -> None:
    """
    Mark human-written claim wording so the audit trail survives re-analysis.

    Guided mode already does this in edit_current_claim. Re-analysis has to do
    the same, or the same human edit is audited in one mode and anonymous in
    the other.
    """
    if not human_edited_claim_ids:
        return

    previous = {claim.id: claim for claim in original.claims}
    edited: list[str] = []

    for claim_id in human_edited_claim_ids:
        claim = next(
            (item for item in replacement.claims if item.id == claim_id),
            None,
        )
        if claim is None:
            raise ValueError(
                f"human-edited claim {claim_id!r} is not part of the replacement step"
            )

        if claim.original_text is None:
            prior = previous.get(claim_id)
            claim.original_text = prior.text if prior is not None else claim.text

        claim.information_type = InformationType.HUMAN_INTERPRETATION
        if claim_id not in edited:
            edited.append(claim_id)

    for claim_id in edited:
        if claim_id not in replacement.human_review.edited_claim_ids:
            replacement.human_review.edited_claim_ids.append(claim_id)


def _replace_step(
    analysis: AnalysisRun,
    *,
    step_id: str,
    result: ReanalysisResult,
    original_version: int,
) -> None:
    index = _step_index(analysis, step_id)
    original = analysis.steps[index]
    replacement = result.step.model_copy(deep=True)

    if replacement.id != original.id:
        raise ValueError("re-analysis must preserve the selected step ID")
    if replacement.kind != original.kind:
        raise ValueError("re-analysis must preserve the selected step kind")
    if replacement.depends_on != original.depends_on:
        raise ValueError("re-analysis must preserve the selected step dependencies")

    _merge_reanalysis_evidence(analysis, result.evidence)

    replacement.version = original_version + 1
    replacement.status = StepStatus.DRAFT
    replacement_claim_ids = {claim.id for claim in replacement.claims}
    preserved_flags = [
        claim_id
        for claim_id in original.human_review.flagged_claim_ids
        if claim_id in replacement_claim_ids
    ]
    replacement.human_review = HumanReview(
        status=HumanReviewStatus.IN_REVIEW,
        notes=[
            *original.human_review.notes,
            f"Re-analysis generated from step version {original_version}.",
        ],
        flagged_claim_ids=preserved_flags,
    )
    # After the fresh HumanReview is attached, or the edit trail is discarded
    # along with the old one.
    _record_human_edits(original, replacement, result.human_edited_claim_ids)

    for claim_id in result.human_edited_claim_ids:
        if claim_id in replacement.human_review.flagged_claim_ids:
            replacement.human_review.flagged_claim_ids.remove(claim_id)
            replacement.human_review.notes.append(
                f"Resolved flag {claim_id}: reviewer edited the wording."
            )

    analysis.steps[index] = replacement


def reanalyze_step(
    analysis: AnalysisRun,
    step_id: str,
    reanalyzer: StepReanalyzer,
) -> AnalysisRun:
    """
    Regenerate exactly one selected step and invalidate only its descendants.

    The reanalyzer receives a validated snapshot plus a deep copy of the selected
    step. It may return replacement step content and new evidence tied to sources
    already present in the run. Upstream and unrelated steps are preserved.
    """
    updated = _validated_copy(analysis)
    original = updated.steps[_step_index(updated, step_id)]
    original_version = original.version

    result = reanalyzer(
        _validated_copy(updated),
        original.model_copy(deep=True),
    )
    if not isinstance(result, ReanalysisResult):
        raise TypeError("step reanalyzer must return ReanalysisResult")

    _replace_step(
        updated,
        step_id=step_id,
        result=result,
        original_version=original_version,
    )
    updated = mark_dependent_steps_needs_refresh(updated, step_id)
    updated.current_step_id = step_id

    return _validated_copy(updated)


def refresh_step(
    analysis: AnalysisRun,
    step_id: str,
    reanalyzer: StepReanalyzer,
) -> AnalysisRun:
    """
    Refresh one stale step once all of its direct dependencies are current.

    This enforces topological refresh order while leaving other stale branches alone.
    """
    checked = _validated_copy(analysis)
    step = checked.steps[_step_index(checked, step_id)]
    if step.status != StepStatus.NEEDS_REFRESH:
        raise ValueError(f"step {step_id!r} is not marked needs_refresh")

    step_map = {item.id: item for item in checked.steps}
    stale_dependencies = [
        dependency
        for dependency in step.depends_on
        if step_map[dependency].status == StepStatus.NEEDS_REFRESH
    ]
    if stale_dependencies:
        raise ValueError(
            f"step {step_id!r} cannot refresh before dependencies: "
            f"{sorted(stale_dependencies)}"
        )

    return reanalyze_step(checked, step_id, reanalyzer)


def _brief_eligible_steps(analysis: AnalysisRun) -> list[AnalysisStep]:
    globally_approved = (
        analysis.final_review_status == HumanReviewStatus.APPROVED
    )
    excluded_kinds = {StepKind.VERIFICATION, StepKind.DRAFT_BRIEF}

    return [
        step
        for step in analysis.steps
        if step.kind not in excluded_kinds
        and (
            globally_approved
            or step.human_review.status
            in {HumanReviewStatus.REVIEWED, HumanReviewStatus.APPROVED}
        )
    ]


def _flag_reason(step: AnalysisStep, claim_id: str) -> str | None:
    prefix = f"Flagged {claim_id}: "
    for note in reversed(step.human_review.notes):
        if note.startswith(prefix):
            return note[len(prefix):].strip() or None
    return None


def _claim_origin(step: AnalysisStep, claim) -> str:
    human_edited = (
        claim.id in step.human_review.edited_claim_ids
        or claim.information_type == InformationType.HUMAN_INTERPRETATION
    )
    return "human-edited" if human_edited else "AI-generated"


def _promotion_block_reason(step: AnalysisStep, claim) -> str | None:
    if not claim.evidence_ids:
        return "No cited evidence is attached to this finding."

    if claim.id in step.human_review.flagged_claim_ids:
        reason = _flag_reason(step, claim.id) or "Reason not recorded."
        return f"Reviewer flag remains unresolved: {reason}"

    if claim.verification_status not in {
        VerificationStatus.SUPPORTED,
        VerificationStatus.PARTIALLY_SUPPORTED,
    }:
        return (
            "Verification status is "
            f"{claim.verification_status.value}; normal report promotion "
            "requires supported or partially_supported."
        )

    return None


def _leadership_claim_line(step: AnalysisStep, claim) -> str:
    labels: list[str] = []
    if _claim_origin(step, claim) == "human-edited":
        labels.append("human-edited")
    if claim.verification_status == VerificationStatus.PARTIALLY_SUPPORTED:
        labels.append("partially supported")
    suffix = f" ({'; '.join(labels)})" if labels else ""
    return f"- {claim.text} [{claim.id}]{suffix}"


def _leadership_report_text(
    analysis: AnalysisRun,
    steps: list[AnalysisStep],
) -> str:
    lines = [
        "PolicyTrace Leadership Report",
        f"Policy: {analysis.policy.title}",
        "",
        (
            "This report contains only reviewed findings that have cited evidence "
            "and passed the report-promotion gate. Stable claim IDs in brackets "
            "link each finding to the Evidence Audit Log."
        ),
    ]

    withheld = 0
    for step in steps:
        promoted = []
        for claim in step.claims:
            if _promotion_block_reason(step, claim) is None:
                promoted.append(claim)
            else:
                withheld += 1

        lines.extend(["", f"## {step.title}"])
        if not promoted:
            lines.append(
                "- No reviewed findings from this section met report-promotion criteria."
            )
            continue

        for claim in promoted:
            lines.append(_leadership_claim_line(step, claim))

    lines.extend(
        [
            "",
            "## Review limitations",
            (
                f"- {withheld} reviewed finding(s) were withheld from this leadership "
                "report because an evidence, verification, or reviewer-flag gate "
                "remains unresolved. See the Evidence Audit Log for the full record."
            ),
        ]
    )
    return "\n".join(lines)


def _append_evidence_receipts(
    lines: list[str],
    *,
    analysis: AnalysisRun,
    evidence_ids: list[str],
) -> None:
    evidence_map = {item.id: item for item in analysis.evidence}
    source_map = {item.id: item for item in analysis.sources}

    if not evidence_ids:
        lines.append("  Evidence receipts: none")
        return

    lines.append("  Evidence receipts:")
    for evidence_id in evidence_ids:
        evidence = evidence_map.get(evidence_id)
        if evidence is None:
            lines.append(f"    - {evidence_id}: missing evidence record")
            continue
        source = source_map.get(evidence.source_id)
        lines.append(f"    - Evidence ID: {evidence.id}")
        if source is None:
            lines.append(f"      Source ID: {evidence.source_id} (missing source record)")
        else:
            lines.append(f"      Source ID: {source.id}")
            lines.append(f"      Source title: {source.title}")
            lines.append(f"      Source type: {source.information_type.value}")
            if source.url:
                lines.append(f"      Source URL: {source.url}")
        lines.append(f"      Locator: {evidence.locator or 'not recorded'}")
        passage = evidence.snippet.replace("\n", "\n        ")
        lines.append("      Exact passage:")
        lines.append(f"        {passage}")


def _append_audit_claim(
    lines: list[str],
    *,
    analysis: AnalysisRun,
    step: AnalysisStep,
    claim,
) -> None:
    origin = _claim_origin(step, claim)
    block_reason = _promotion_block_reason(step, claim)
    lines.extend(
        [
            f"- Claim ID: {claim.id}",
            f"  Origin: {origin}",
            f"  Claim: {claim.text}",
            f"  Verification: {claim.verification_status.value}",
            (
                "  Report promotion: INCLUDED"
                if block_reason is None
                else f"  Report promotion: BLOCKED — {block_reason}"
            ),
        ]
    )
    if claim.verification_note:
        lines.append(f"  Verification note: {claim.verification_note}")
    if claim.confidence:
        lines.append(f"  Model confidence: {claim.confidence}")
    if origin == "human-edited" and claim.original_text:
        lines.append(f"  Original AI wording: {claim.original_text}")
    if claim.id in step.human_review.flagged_claim_ids:
        reason = _flag_reason(step, claim.id) or "Reason not recorded."
        lines.append(f"  FLAGGED BY REVIEWER: {reason}")

    _append_evidence_receipts(
        lines,
        analysis=analysis,
        evidence_ids=claim.evidence_ids,
    )


def _audit_log_text(
    analysis: AnalysisRun,
    steps: list[AnalysisStep],
) -> str:
    lines = [
        "PolicyTrace Evidence Audit Log",
        f"Policy: {analysis.policy.title}",
        f"Analysis run: {analysis.id}",
        f"Final human review status: {analysis.final_review_status.value}",
        "",
        (
            "This log preserves every reviewed structured finding, including "
            "findings withheld from the leadership report. Evidence receipts "
            "include the exact stored passage and source metadata."
        ),
    ]

    for step in steps:
        lines.extend(
            [
                "",
                f"## {step.title}",
                f"Step ID: {step.id}",
                f"Step version: {step.version}",
                f"Step status: {step.status.value}",
                f"Human review: {step.human_review.status.value}",
            ]
        )
        if not step.claims:
            lines.append("- No structured claims in this reviewed section.")
        else:
            for claim in step.claims:
                _append_audit_claim(
                    lines,
                    analysis=analysis,
                    step=step,
                    claim=claim,
                )

        if step.human_review.notes:
            lines.append("Review notes:")
            for note in step.human_review.notes:
                lines.append(f"- {note}")

    return "\n".join(lines)


def build_leadership_report_text(analysis: AnalysisRun) -> str:
    checked = _validated_copy(analysis)
    steps = _brief_eligible_steps(checked)
    if not steps:
        raise ValueError("cannot build leadership report without reviewed or accepted steps")
    return _leadership_report_text(checked, steps)


def build_evidence_audit_log(analysis: AnalysisRun) -> str:
    checked = _validated_copy(analysis)
    steps = _brief_eligible_steps(checked)
    if not steps:
        raise ValueError("cannot build evidence audit log without reviewed or accepted steps")
    return _audit_log_text(checked, steps)

def build_final_brief(analysis: AnalysisRun) -> AnalysisRun:
    """
    Build the deterministic leadership-report draft without generating new claims.

    Only reviewed findings that pass the evidence/verification promotion gate are
    included in the leadership layer. Full receipts remain available separately in
    the Evidence Audit Log.
    """
    updated = _validated_copy(analysis)

    stale_steps = [
        step.id
        for step in updated.steps
        if step.status == StepStatus.NEEDS_REFRESH
        and step.kind not in {StepKind.VERIFICATION, StepKind.DRAFT_BRIEF}
    ]
    if stale_steps:
        raise ValueError(
            "cannot build final brief while steps need refresh: "
            f"{sorted(stale_steps)}"
        )

    eligible = _brief_eligible_steps(updated)
    if not eligible:
        raise ValueError("cannot build final brief without reviewed or accepted steps")

    previous_briefs = [
        step for step in updated.steps if step.kind == StepKind.DRAFT_BRIEF
    ]
    previous_version = max((step.version for step in previous_briefs), default=0)
    updated.steps = [
        step for step in updated.steps if step.kind != StepKind.DRAFT_BRIEF
    ]

    brief = AnalysisStep(
        id="step-draft-brief",
        kind=StepKind.DRAFT_BRIEF,
        title="Final policy brief",
        status=StepStatus.DRAFT,
        depends_on=[step.id for step in eligible],
        claims=[],
        ai_output=_leadership_report_text(updated, eligible),
        human_review=HumanReview(status=HumanReviewStatus.IN_REVIEW),
        version=previous_version + 1,
    )
    updated.steps.append(brief)
    updated.current_step_id = brief.id
    updated.final_review_status = HumanReviewStatus.IN_REVIEW

    return _validated_copy(updated)
