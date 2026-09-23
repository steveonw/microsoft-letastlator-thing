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
    StepKind,
    StepStatus,
)


@dataclass(frozen=True)
class ReanalysisResult:
    """One regenerated step plus any new evidence it created."""

    step: AnalysisStep
    evidence: tuple[Evidence, ...] = field(default_factory=tuple)


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
    replacement.human_review = HumanReview(
        status=HumanReviewStatus.IN_REVIEW,
        notes=[
            *original.human_review.notes,
            f"Re-analysis generated from step version {original_version}.",
        ],
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


def _brief_text(analysis: AnalysisRun, steps: list[AnalysisStep]) -> str:
    lines = [
        f"Policy: {analysis.policy.title}",
        "",
        (
            "This draft contains only reviewed or accepted structured findings. "
            "Claim wording is copied verbatim from the reviewed AnalysisRun."
        ),
    ]

    for step in steps:
        lines.extend(
            [
                "",
                f"## {step.title}",
                f"Step: {step.id} (version {step.version})",
            ]
        )
        if not step.claims:
            lines.append("- No structured claims in this reviewed section.")
            continue

        for claim in step.claims:
            evidence = ", ".join(claim.evidence_ids) if claim.evidence_ids else "none"
            lines.extend(
                [
                    f"- [{claim.id}] {claim.text}",
                    f"  Verification: {claim.verification_status.value}",
                    f"  Evidence: {evidence}",
                ]
            )

    return "\n".join(lines)


def build_final_brief(analysis: AnalysisRun) -> AnalysisRun:
    """
    Build a traceable final-brief draft without generating new policy claims.

    The assembler copies reviewed/accepted claim text exactly and labels each copied
    finding with its original claim ID, verification status, and evidence IDs.
    """
    updated = _validated_copy(analysis)

    stale_steps = [
        step.id
        for step in updated.steps
        if step.status == StepStatus.NEEDS_REFRESH
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
        ai_output=_brief_text(updated, eligible),
        human_review=HumanReview(status=HumanReviewStatus.IN_REVIEW),
        version=previous_version + 1,
    )
    updated.steps.append(brief)
    updated.current_step_id = brief.id
    updated.final_review_status = HumanReviewStatus.IN_REVIEW

    return _validated_copy(updated)
