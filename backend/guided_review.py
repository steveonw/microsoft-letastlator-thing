from __future__ import annotations

from collections.abc import Callable

from claim_verifier import (
    CLAIM_VERIFIER_SYSTEM_PROMPT,
    build_claim_verification_prompt,
    citation_integrity_problem,
    parse_claim_verification,
)
from models import (
    AnalysisMode,
    AnalysisRun,
    Claim,
    HumanReviewStatus,
    InformationType,
    StepStatus,
    VerificationStatus,
)


def _validated_copy(analysis: AnalysisRun) -> AnalysisRun:
    return AnalysisRun.model_validate(analysis.model_dump(mode="python"))


def _current_step(analysis: AnalysisRun):
    if analysis.current_step_id is None:
        raise ValueError("guided review has no current step")
    for step in analysis.steps:
        if step.id == analysis.current_step_id:
            return step
    raise ValueError(f"current step {analysis.current_step_id!r} does not exist")


def _claim_in_current_step(analysis: AnalysisRun, claim_id: str) -> Claim:
    step = _current_step(analysis)
    for claim in step.claims:
        if claim.id == claim_id:
            return claim
    raise ValueError(
        f"claim {claim_id!r} is not part of current step {step.id!r}"
    )


def begin_guided_review(
    analysis: AnalysisRun,
    *,
    step_id: str | None = None,
) -> AnalysisRun:
    """
    Start or resume human-guided review without silently advancing the run.

    By default, review starts at the first step that has not already been reviewed
    or approved. Passing step_id is explicit human navigation and never changes any
    other step's review state.
    """
    reviewed = _validated_copy(analysis)
    reviewed.mode = AnalysisMode.GUIDED

    if step_id is None:
        candidate = next(
            (
                step
                for step in reviewed.steps
                if step.human_review.status
                not in {
                    HumanReviewStatus.REVIEWED,
                    HumanReviewStatus.APPROVED,
                }
            ),
            None,
        )
        reviewed.current_step_id = candidate.id if candidate else None
    else:
        if step_id not in {step.id for step in reviewed.steps}:
            raise ValueError(f"unknown guided-review step {step_id!r}")
        reviewed.current_step_id = step_id

    if reviewed.current_step_id is not None:
        step = _current_step(reviewed)
        if step.human_review.status == HumanReviewStatus.NOT_REVIEWED:
            step.human_review.status = HumanReviewStatus.IN_REVIEW

    return _validated_copy(reviewed)


def clarify_current_step(analysis: AnalysisRun, note: str) -> AnalysisRun:
    clarification = note.strip()
    if not clarification:
        raise ValueError("clarification note must not be empty")

    reviewed = _validated_copy(analysis)
    step = _current_step(reviewed)
    step.human_review.status = HumanReviewStatus.IN_REVIEW
    step.human_review.notes.append(f"Clarification: {clarification}")

    return _validated_copy(reviewed)


def edit_current_claim(
    analysis: AnalysisRun,
    claim_id: str,
    new_text: str,
) -> AnalysisRun:
    replacement = new_text.strip()
    if not replacement:
        raise ValueError("edited claim text must not be empty")

    reviewed = _validated_copy(analysis)
    step = _current_step(reviewed)
    claim = _claim_in_current_step(reviewed, claim_id)

    if claim.original_text is None:
        claim.original_text = claim.text
    claim.text = replacement
    claim.information_type = InformationType.HUMAN_INTERPRETATION
    claim.verification_status = VerificationStatus.NEEDS_HUMAN_REVIEW
    claim.verification_note = "Human edit requires re-verification."

    if claim.id not in step.human_review.edited_claim_ids:
        step.human_review.edited_claim_ids.append(claim.id)

    step.human_review.status = HumanReviewStatus.IN_REVIEW
    step.status = StepStatus.DRAFT
    step.version += 1

    return _validated_copy(reviewed)


def flag_current_claim(
    analysis: AnalysisRun,
    claim_id: str,
    note: str | None = None,
) -> AnalysisRun:
    reviewed = _validated_copy(analysis)
    step = _current_step(reviewed)
    claim = _claim_in_current_step(reviewed, claim_id)

    if claim.id not in step.human_review.flagged_claim_ids:
        step.human_review.flagged_claim_ids.append(claim.id)

    if note is not None and note.strip():
        step.human_review.notes.append(
            f"Flagged {claim.id}: {note.strip()}"
        )

    step.human_review.status = HumanReviewStatus.IN_REVIEW

    return _validated_copy(reviewed)


def verify_current_claim(
    analysis: AnalysisRun,
    claim_id: str,
    model_call: Callable[[str, str], str],
) -> AnalysisRun:
    """
    Run the separate semantic verifier for only the human-selected current claim.

    The current step never advances. Deterministic evidence integrity is checked
    first; a failed gate stays visible as needs_human_review.
    """
    reviewed = _validated_copy(analysis)
    step = _current_step(reviewed)
    claim = _claim_in_current_step(reviewed, claim_id)

    problem = citation_integrity_problem(reviewed, claim)
    if problem:
        claim.verification_status = VerificationStatus.NEEDS_HUMAN_REVIEW
        claim.verification_note = (
            "Semantic verification was not attempted because the deterministic "
            f"citation-integrity gate failed: {problem}."
        )
    else:
        raw = model_call(
            CLAIM_VERIFIER_SYSTEM_PROMPT,
            build_claim_verification_prompt(reviewed, claim),
        )
        try:
            result = parse_claim_verification(raw)
        except ValueError as exc:
            claim.verification_status = VerificationStatus.NEEDS_HUMAN_REVIEW
            detail = str(exc).splitlines()[0].strip()
            claim.verification_note = (
                "Semantic verification could not be completed because the verifier "
                f"returned an unparseable or schema-invalid response: {detail}. "
                "The claim remains for human review; no verification status was inferred."
            )
            step.human_review.status = HumanReviewStatus.IN_REVIEW
            return _validated_copy(reviewed)

        claim.verification_status = result.status
        claim.verification_note = f"Semantic verification: {result.explanation}"
        if result.narrower_wording:
            claim.verification_note += (
                f" Suggested narrower wording: {result.narrower_wording}"
            )

    step.human_review.status = HumanReviewStatus.IN_REVIEW
    return _validated_copy(reviewed)


def next_guided_step(analysis: AnalysisRun) -> AnalysisRun:
    """
    Advance only in response to the explicit human Next action.

    The current step is marked reviewed. The next step enters in_review. When the
    last step is completed, current_step_id becomes None and final review remains
    untouched for later explicit human approval.
    """
    reviewed = _validated_copy(analysis)
    step = _current_step(reviewed)

    current_index = next(
        index
        for index, item in enumerate(reviewed.steps)
        if item.id == step.id
    )

    step.human_review.status = HumanReviewStatus.REVIEWED

    next_index = current_index + 1
    if next_index >= len(reviewed.steps):
        reviewed.current_step_id = None
        return _validated_copy(reviewed)

    next_step = reviewed.steps[next_index]
    reviewed.current_step_id = next_step.id
    if next_step.human_review.status == HumanReviewStatus.NOT_REVIEWED:
        next_step.human_review.status = HumanReviewStatus.IN_REVIEW

    return _validated_copy(reviewed)


def evidence_for_current_claim(
    analysis: AnalysisRun,
    claim_id: str,
):
    """
    Return the current claim's evidence paired with sources for Show Sources.
    """
    claim = _claim_in_current_step(analysis, claim_id)
    evidence_map = {item.id: item for item in analysis.evidence}
    source_map = {source.id: source for source in analysis.sources}

    result = []
    for evidence_id in claim.evidence_ids:
        evidence = evidence_map[evidence_id]
        result.append((evidence, source_map[evidence.source_id]))
    return result
