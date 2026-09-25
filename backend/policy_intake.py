from __future__ import annotations

import json
import re
from datetime import date, datetime, timezone
from typing import Any, Literal
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from pydantic import BaseModel, ConfigDict, Field

from federal_register import (
    DEFAULT_USER_AGENT,
    NormalizedPolicyDocument,
    fetch_and_normalize,
)
from models import ReportStandard
from policy_status import FederalRegisterDocumentRef, PolicyStatusSnapshot


FEDERAL_REGISTER_SEARCH_API = "https://www.federalregister.gov/api/v1/documents.json"
MAX_SEARCH_RESULTS = 8
PROJECT_SCHEMA_VERSION = 1


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PolicySearchResult(StrictModel):
    document_number: str
    title: str
    document_type: str | None = None
    action: str | None = None
    publication_date: date | None = None
    agency_names: list[str] = Field(default_factory=list)
    regulation_id_numbers: list[str] = Field(default_factory=list)
    html_url: str | None = None


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
    news_query: str = ""
    max_articles: int = Field(default=8, ge=1, le=25)
    comparison_document_number: str = ""
    report_standard: ReportStandard = ReportStandard.BALANCED


class PolicyTraceProject(StrictModel):
    policytrace_project_schema: Literal[1] = PROJECT_SCHEMA_VERSION
    saved_at: datetime
    search_query: str = ""
    primary_document_number: str
    intake_plan: IntakePlan
    excluded_media_claim_ids: list[str] = Field(default_factory=list)


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _agency_names(row: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for agency in row.get("agencies") or []:
        if isinstance(agency, dict) and agency.get("name"):
            names.append(str(agency["name"]))
    if not names:
        for value in row.get("agency_names") or []:
            if value:
                names.append(str(value))
    return names


def _strings(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if item]
    return [str(value)]


def search_federal_register(
    query: str,
    *,
    limit: int = MAX_SEARCH_RESULTS,
    timeout: int = 20,
) -> list[PolicySearchResult]:
    query = query.strip()
    if not query:
        raise ValueError("Enter a Federal Register search term")
    if limit < 1 or limit > MAX_SEARCH_RESULTS:
        raise ValueError(f"limit must be between 1 and {MAX_SEARCH_RESULTS}")

    params = {
        "per_page": limit,
        "conditions[term]": query,
    }
    request = Request(
        f"{FEDERAL_REGISTER_SEARCH_API}?{urlencode(params)}",
        headers={
            "User-Agent": DEFAULT_USER_AGENT,
            "Accept": "application/json",
        },
    )
    with urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))

    rows = payload.get("results")
    if not isinstance(rows, list):
        raise ValueError("Federal Register search returned no results list")

    results: list[PolicySearchResult] = []
    for row in rows[:limit]:
        if not isinstance(row, dict):
            continue
        number = row.get("document_number")
        title = row.get("title")
        if not number or not title:
            continue
        results.append(
            PolicySearchResult(
                document_number=str(number),
                title=str(title),
                document_type=row.get("type"),
                action=row.get("action"),
                publication_date=_parse_date(row.get("publication_date")),
                agency_names=_agency_names(row),
                regulation_id_numbers=_strings(row.get("regulation_id_numbers")),
                html_url=row.get("html_url"),
            )
        )
    return results


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
                if overlap < 0.22 and not same_agency:
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
