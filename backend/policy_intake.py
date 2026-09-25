from __future__ import annotations

import re
from datetime import date, datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from federal_register import (
    DEFAULT_SEARCH_TYPES,
    DocketDetection,
    NormalizedPolicyDocument,
    SearchCandidate,
    detect_document_docket,
    fetch_and_normalize,
    search_documents,
)
from models import ReportStandard
from policy_status import FederalRegisterDocumentRef, PolicyStatusSnapshot


MAX_SEARCH_RESULTS = 8
PROJECT_SCHEMA_VERSION = 1


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RelatedDocumentSuggestion(StrictModel):
    document_number: str
    title: str
    document_type: str | None = None
    action: str | None = None
    publication_date: date | None = None
    html_url: str | None = None
    relationship_strength: Literal["strong", "moderate", "possible"]
    reasons: list[str] = Field(default_factory=list)


class WorkloadEstimate(StrictModel):
    primary_document_number: str
    comparison_document_number: str
    primary_characters: int = Field(ge=0)
    comparison_characters: int = Field(ge=0)
    primary_units: int = Field(ge=0)
    comparison_units: int = Field(ge=0)
    relative_size: float = Field(ge=0)
    workload: Literal["normal", "moderate", "large", "very_large"]
    confirmation_steps: int = Field(ge=0, le=2)
    warning: str | None = None


class IntakePlan(StrictModel):
    include_current_status: bool = True
    include_comments: bool = True
    include_news: bool = True
    include_comparison: bool = False
    docket_id: str = ""
    max_comments: int = Field(default=12, ge=1, le=100)
    comment_sampling_method: Literal["earliest", "random"] = "earliest"
    comment_sampling_seed: int | None = Field(default=None, ge=0, le=2**63 - 1)
    news_query: str = ""
    max_articles: int = Field(default=8, ge=1, le=25)
    comparison_document_number: str = ""
    report_standard: ReportStandard = ReportStandard.BALANCED


class PolicyTraceProject(StrictModel):
    policytrace_project_schema: Literal[1] = PROJECT_SCHEMA_VERSION
    saved_at: datetime
    search_query: str = ""
    include_notices: bool = False
    primary_document_number: str
    intake_plan: IntakePlan
    excluded_media_claim_ids: list[str] = Field(default_factory=list)


def search_federal_register(
    query: str,
    *,
    limit: int = MAX_SEARCH_RESULTS,
    timeout: int = 20,
    include_notices: bool = False,
) -> list[SearchCandidate]:
    document_types = list(DEFAULT_SEARCH_TYPES)
    if include_notices:
        document_types.append("NOTICE")
    result = search_documents(
        query,
        document_types=document_types,
        limit=limit,
        timeout=timeout,
    )
    return result.candidates


def intake_docket_detection(
    document: NormalizedPolicyDocument,
) -> DocketDetection:
    return detect_document_docket(document)


def _title_tokens(value: str) -> set[str]:
    stop = {
        "a", "an", "and", "for", "in", "of", "on", "or", "the", "to", "with",
        "rule", "notice", "proposed", "final",
    }
    return {
        token
        for token in re.findall(r"[a-z0-9]+", value.casefold())
        if len(token) >= 3 and token not in stop
    }


def _title_overlap(left: str, right: str) -> float:
    a = _title_tokens(left)
    b = _title_tokens(right)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _ref_to_suggestion(
    ref: FederalRegisterDocumentRef,
    *,
    current: NormalizedPolicyDocument,
    reasons: list[str],
    strength: Literal["strong", "moderate", "possible"],
) -> RelatedDocumentSuggestion:
    when = ref.publication_date
    if (
        when is not None
        and current.publication_date is not None
        and when != current.publication_date
    ):
        reasons.append(
            "published later than selected document"
            if when > current.publication_date
            else "published earlier than selected document"
        )
    return RelatedDocumentSuggestion(
        document_number=ref.document_number,
        title=ref.title,
        document_type=ref.document_type,
        action=ref.action,
        publication_date=ref.publication_date,
        html_url=ref.html_url,
        relationship_strength=strength,
        reasons=reasons,
    )


def related_document_suggestions(
    document: NormalizedPolicyDocument,
    status: PolicyStatusSnapshot | None,
    *,
    limit: int = MAX_SEARCH_RESULTS,
    timeout: int = 20,
) -> list[RelatedDocumentSuggestion]:
    suggestions: list[RelatedDocumentSuggestion] = []
    seen = {document.document_number}

    if status is not None:
        for ref in status.federal_register_documents:
            if ref.document_number in seen:
                continue
            seen.add(ref.document_number)
            reasons = []
            if status.rin:
                reasons.append(f"same RIN: {status.rin}")
            suggestions.append(
                _ref_to_suggestion(
                    ref,
                    current=document,
                    reasons=reasons,
                    strength="strong",
                )
            )
            if len(suggestions) >= limit:
                return suggestions

    # If the RIN family is small or absent, provide clearly weaker title-based
    # candidates rather than pretending they are part of the same rulemaking.
    if len(suggestions) < limit:
        tokens = sorted(
            _title_tokens(document.title),
            key=lambda value: (-len(value), value),
        )
        fallback_query = " ".join(tokens[:5])
        if fallback_query:
            try:
                candidates = search_federal_register(
                    fallback_query,
                    limit=limit,
                    timeout=timeout,
                )
            except Exception:
                candidates = []
            current_agencies = {name.casefold() for name in document.agency_names}
            for candidate in candidates:
                if candidate.document_number in seen:
                    continue
                overlap = _title_overlap(document.title, candidate.title)
                candidate_agencies = {
                    name.casefold() for name in candidate.agency_names
                }
                same_agency = bool(current_agencies & candidate_agencies)
                # Same agency is corroborating context, not enough by itself.
                # Require meaningful title/topic overlap before suggesting a
                # document outside the deterministic RIN family.
                if overlap < 0.22:
                    continue
                reasons = []
                if same_agency:
                    reasons.append("same agency")
                if overlap >= 0.45:
                    reasons.append("high title similarity")
                    strength: Literal["moderate", "possible"] = "moderate"
                else:
                    reasons.append("possible title/topic relationship")
                    strength = "possible"
                if (
                    candidate.publication_date is not None
                    and document.publication_date is not None
                ):
                    reasons.append(
                        "published later than selected document"
                        if candidate.publication_date > document.publication_date
                        else "published earlier than selected document"
                    )
                suggestions.append(
                    RelatedDocumentSuggestion(
                        document_number=candidate.document_number,
                        title=candidate.title,
                        document_type=candidate.document_type,
                        action=candidate.action,
                        publication_date=candidate.publication_date,
                        html_url=candidate.html_url,
                        relationship_strength=strength,
                        reasons=reasons,
                    )
                )
                seen.add(candidate.document_number)
                if len(suggestions) >= limit:
                    break

    return suggestions


def estimate_comparison_workload(
    primary: NormalizedPolicyDocument,
    comparison_document_number: str,
    *,
    timeout: int = 30,
) -> tuple[WorkloadEstimate, NormalizedPolicyDocument]:
    comparison_document_number = comparison_document_number.strip()
    if not comparison_document_number:
        raise ValueError("Choose a comparison document first")
    if comparison_document_number == primary.document_number:
        raise ValueError("Comparison document must differ from the primary document")

    comparison = fetch_and_normalize(
        comparison_document_number,
        timeout=timeout,
    )
    primary_chars = len(primary.raw_text)
    comparison_chars = len(comparison.raw_text)
    denominator = max(1, primary_chars)
    ratio = comparison_chars / denominator

    if ratio < 2:
        workload = "normal"
        confirmations = 0
        warning = None
    elif ratio < 3:
        workload = "moderate"
        confirmations = 0
        warning = (
            "The comparison document is noticeably larger than the primary "
            "document, but no extra confirmation is required."
        )
    elif ratio < 5:
        workload = "large"
        confirmations = 1
        warning = (
            "This comparison document is at least 3x the size of the primary "
            "document and may take significantly longer to compare."
        )
    else:
        workload = "very_large"
        confirmations = 2
        warning = (
            "This comparison document is at least 5x the size of the primary "
            "document. Expect substantially more processing time."
        )

    return (
        WorkloadEstimate(
            primary_document_number=primary.document_number,
            comparison_document_number=comparison.document_number,
            primary_characters=primary_chars,
            comparison_characters=comparison_chars,
            primary_units=len(primary.chunks),
            comparison_units=len(comparison.chunks),
            relative_size=round(ratio, 2),
            workload=workload,
            confirmation_steps=confirmations,
            warning=warning,
        ),
        comparison,
    )


def bounded_preview_excerpt(
    document: NormalizedPolicyDocument,
    *,
    max_chars: int = 1800,
) -> str:
    if max_chars < 500 or max_chars > 2500:
        raise ValueError("preview excerpt must be between 500 and 2500 characters")
    text = document.raw_text.strip()
    return text[:max_chars]


def validate_project(value: dict[str, Any]) -> PolicyTraceProject:
    project = PolicyTraceProject.model_validate(value)
    # Saved project files recreate an intake plan only. Credentials are
    # intentionally not part of this schema and extra fields are rejected.
    return project


def new_project(
    *,
    search_query: str,
    primary_document_number: str,
    intake_plan: IntakePlan,
    excluded_media_claim_ids: list[str] | None = None,
) -> PolicyTraceProject:
    return PolicyTraceProject(
        saved_at=datetime.now(timezone.utc),
        search_query=search_query.strip(),
        primary_document_number=primary_document_number.strip(),
        intake_plan=intake_plan,
        excluded_media_claim_ids=list(excluded_media_claim_ids or []),
    )
