from __future__ import annotations

from collections.abc import Callable

from claim_verifier import verify_analysis
from models import (
    AnalysisMode,
    AnalysisRun,
    HumanReviewStatus,
)


def _validated_copy(analysis: AnalysisRun) -> AnalysisRun:
    return AnalysisRun.model_validate(analysis.model_dump(mode="python"))


def _merge_unique(items, *, kind: str):
    merged = {}
    for item in items:
        existing = merged.get(item.id)
        if existing is None:
            merged[item.id] = item.model_copy(deep=True)
            continue
        if existing.model_dump(mode="python") != item.model_dump(mode="python"):
            raise ValueError(f"conflicting duplicate {kind} ID {item.id}")
    return list(merged.values())


def combine_analysis_runs(
    policy_analysis: AnalysisRun,
    response_analysis: AnalysisRun,
) -> AnalysisRun:
    """
    Combine the shared policy and response pipelines into one Rush AnalysisRun.

    The two inputs must describe the same policy. Duplicate source/evidence IDs are
    deduplicated only when their full contents agree.
    """
    policy = _validated_copy(policy_analysis)
    responses = _validated_copy(response_analysis)

    if policy.policy.id != responses.policy.id:
        raise ValueError("rush inputs describe different policies")

    policy_steps = [
        step.model_copy(deep=True)
        for step in policy.steps
        if step.kind.value != "verification"
    ]
    response_steps = [
        step.model_copy(deep=True)
        for step in responses.steps
        if step.kind.value != "verification"
    ]

    policy_step_ids = {step.id for step in policy_steps}
    if response_steps:
        first_response = response_steps[0]
        if not first_response.depends_on:
            preferred = [
                step_id
                for step_id in (
                    "step-stakeholders",
                    "step-affected-programs",
                )
                if step_id in policy_step_ids
            ]
            if not preferred and policy_steps:
                preferred = [policy_steps[-1].id]
            first_response.depends_on = preferred

    combined = AnalysisRun(
        id=f"rush-{policy.id}",
        mode=AnalysisMode.RUSH,
        policy=policy.policy.model_copy(deep=True),
        sources=_merge_unique(
            [*policy.sources, *responses.sources],
            kind="source",
        ),
        evidence=_merge_unique(
            [*policy.evidence, *responses.evidence],
            kind="evidence",
        ),
        steps=[*policy_steps, *response_steps],
        current_step_id=None,
        final_review_status=HumanReviewStatus.NOT_REVIEWED,
    )
    return _validated_copy(combined)


def run_rush_analysis(
    policy_analysis: AnalysisRun,
    response_analysis: AnalysisRun,
    verifier_model_call: Callable[[str, str], str],
) -> AnalysisRun:
    """
    Auto-run the shared sections through semantic verification, then stop.

    Rush Mode never marks the final result approved. Instead it lands at
    final_review_status=in_review with no current analysis step selected.
    """
    combined = combine_analysis_runs(policy_analysis, response_analysis)
    verified = verify_analysis(combined, verifier_model_call)

    verified.mode = AnalysisMode.RUSH
    verified.current_step_id = None
    verified.final_review_status = HumanReviewStatus.IN_REVIEW

    for step in verified.steps:
        step.human_review.status = HumanReviewStatus.NOT_REVIEWED

    return _validated_copy(verified)


def open_rush_step_for_review(
    analysis: AnalysisRun,
    step_id: str,
) -> AnalysisRun:
    """
    Explicitly open any saved Rush section for human inspection/editing.
    """
    reviewed = _validated_copy(analysis)
    if reviewed.mode != AnalysisMode.RUSH:
        raise ValueError("analysis is not in rush mode")

    step = next((item for item in reviewed.steps if item.id == step_id), None)
    if step is None:
        raise ValueError(f"unknown rush step {step_id!r}")

    reviewed.current_step_id = step.id
    if step.human_review.status == HumanReviewStatus.NOT_REVIEWED:
        step.human_review.status = HumanReviewStatus.IN_REVIEW

    return _validated_copy(reviewed)


def return_to_rush_final_review(analysis: AnalysisRun) -> AnalysisRun:
    reviewed = _validated_copy(analysis)
    if reviewed.mode != AnalysisMode.RUSH:
        raise ValueError("analysis is not in rush mode")
    reviewed.current_step_id = None
    reviewed.final_review_status = HumanReviewStatus.IN_REVIEW
    return _validated_copy(reviewed)


def approve_rush_final_review(analysis: AnalysisRun) -> AnalysisRun:
    """
    Explicit human approval gate. This is never called by run_rush_analysis.
    """
    reviewed = _validated_copy(analysis)
    if reviewed.mode != AnalysisMode.RUSH:
        raise ValueError("analysis is not in rush mode")
    if reviewed.final_review_status != HumanReviewStatus.IN_REVIEW:
        raise ValueError("rush analysis is not awaiting final human review")

    reviewed.current_step_id = None
    reviewed.final_review_status = HumanReviewStatus.APPROVED
    return _validated_copy(reviewed)
