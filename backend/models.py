from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AnalysisMode(str, Enum):
    GUIDED = "guided"
    RUSH = "rush"


class InformationType(str, Enum):
    OFFICIAL_POLICY = "official_policy"
    OFFICIAL_CONTEXT = "official_context"
    FACTUAL_REPORTING = "factual_reporting"
    PUBLIC_OPINION = "public_opinion"
    STAKEHOLDER_CLAIM = "stakeholder_claim"
    AI_INTERPRETATION = "ai_interpretation"
    HUMAN_INTERPRETATION = "human_interpretation"
    UNVERIFIED = "unverified"


class VerificationStatus(str, Enum):
    SUPPORTED = "supported"
    PARTIALLY_SUPPORTED = "partially_supported"
    NEEDS_CLARIFICATION = "needs_clarification"
    UNSUPPORTED = "unsupported"
    NEEDS_HUMAN_REVIEW = "needs_human_review"


class StepStatus(str, Enum):
    DRAFT = "draft"
    VERIFIED = "verified"
    NEEDS_REFRESH = "needs_refresh"


class HumanReviewStatus(str, Enum):
    NOT_REVIEWED = "not_reviewed"
    IN_REVIEW = "in_review"
    REVIEWED = "reviewed"
    APPROVED = "approved"


class PiiRedactionStatus(str, Enum):
    NOT_CHECKED = "not_checked"
    NOT_DETECTED = "not_detected"
    REDACTED = "redacted"
    NOT_APPLICABLE = "not_applicable"


class StepKind(str, Enum):
    POLICY_UNDERSTANDING = "policy_understanding"
    MAJOR_PROVISIONS = "major_provisions"
    STAKEHOLDERS = "stakeholders"
    AFFECTED_PROGRAMS = "affected_programs"
    PUBLIC_RESPONSE = "public_response"
    THEMES_VIEWPOINTS = "themes_viewpoints"
    FACTUAL_REPORTING = "factual_reporting"
    VERIFICATION = "verification"
    DRAFT_BRIEF = "draft_brief"


Confidence = Literal["low", "medium", "high"]


class Policy(StrictModel):
    id: str
    title: str
    jurisdiction: str
    version: str | None = None
    source_ids: list[str] = Field(default_factory=list)


class Source(StrictModel):
    id: str
    title: str
    information_type: InformationType
    url: HttpUrl | None = None
    agency: str | None = None
    published_at: date | None = None
    submitted_at: datetime | None = None
    version: str | None = None
    raw_text: str | None = None
    pii_redaction_status: PiiRedactionStatus = PiiRedactionStatus.NOT_CHECKED
    duplicate_cluster_id: str | None = None


class Evidence(StrictModel):
    id: str
    source_id: str
    snippet: str
    locator: str | None = None
    start_offset: int | None = Field(default=None, ge=0)
    end_offset: int | None = Field(default=None, ge=0)
    retrieved_at: datetime

    @model_validator(mode="after")
    def check_offsets(self) -> "Evidence":
        if (self.start_offset is None) != (self.end_offset is None):
            raise ValueError("start_offset and end_offset must be provided together")
        if (
            self.start_offset is not None
            and self.end_offset is not None
            and self.end_offset <= self.start_offset
        ):
            raise ValueError("end_offset must be greater than start_offset")
        return self


class Claim(StrictModel):
    id: str
    text: str
    original_text: str | None = None
    information_type: InformationType
    evidence_ids: list[str] = Field(default_factory=list)
    verification_status: VerificationStatus
    verification_note: str | None = None
    confidence: Confidence

    @model_validator(mode="after")
    def require_verification_note_when_not_supported(self) -> "Claim":
        if (
            self.verification_status != VerificationStatus.SUPPORTED
            and not self.verification_note
        ):
            raise ValueError(
                "verification_note is required unless verification_status is supported"
            )
        return self


class HumanReview(StrictModel):
    status: HumanReviewStatus = HumanReviewStatus.NOT_REVIEWED
    notes: list[str] = Field(default_factory=list)
    flagged_claim_ids: list[str] = Field(default_factory=list)
    edited_claim_ids: list[str] = Field(default_factory=list)


class AnalysisStep(StrictModel):
    id: str
    kind: StepKind
    title: str
    status: StepStatus = StepStatus.DRAFT
    depends_on: list[str] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)
    ai_output: str | None = None
    human_review: HumanReview = Field(default_factory=HumanReview)
    version: int = Field(default=1, ge=1)


class AnalysisRun(StrictModel):
    schema_version: Literal["0.2.0"] = "0.2.0"
    id: str
    mode: AnalysisMode
    policy: Policy
    sources: list[Source] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    steps: list[AnalysisStep] = Field(default_factory=list)
    current_step_id: str | None = None
    final_review_status: HumanReviewStatus = HumanReviewStatus.NOT_REVIEWED

    @model_validator(mode="after")
    def check_references_and_evidence(self) -> "AnalysisRun":
        source_ids = [source.id for source in self.sources]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("source IDs must be unique")
        source_map = {source.id: source for source in self.sources}

        missing_policy_sources = set(self.policy.source_ids) - set(source_map)
        if missing_policy_sources:
            raise ValueError(
                f"policy references missing source IDs: {sorted(missing_policy_sources)}"
            )

        evidence_ids = [item.id for item in self.evidence]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("evidence IDs must be unique")
        evidence_map = {item.id: item for item in self.evidence}

        for item in self.evidence:
            source = source_map.get(item.source_id)
            if source is None:
                raise ValueError(
                    f"{item.id} references missing source ID {item.source_id}"
                )

            if source.raw_text is not None:
                if item.start_offset is not None and item.end_offset is not None:
                    if item.end_offset > len(source.raw_text):
                        raise ValueError(
                            f"{item.id} offsets exceed source text length"
                        )
                    if source.raw_text[item.start_offset:item.end_offset] != item.snippet:
                        raise ValueError(
                            f"{item.id} snippet does not match source text at stored offsets"
                        )
                elif item.snippet not in source.raw_text:
                    raise ValueError(
                        f"{item.id} snippet does not appear in source raw_text"
                    )

        step_ids = [step.id for step in self.steps]
        if len(step_ids) != len(set(step_ids)):
            raise ValueError("analysis step IDs must be unique")
        step_id_set = set(step_ids)

        if self.current_step_id is not None and self.current_step_id not in step_id_set:
            raise ValueError(
                f"current_step_id references missing step {self.current_step_id}"
            )

        all_claim_ids: list[str] = []
        graph: dict[str, list[str]] = {}

        for step in self.steps:
            graph[step.id] = step.depends_on
            if step.id in step.depends_on:
                raise ValueError(f"{step.id} cannot depend on itself")

            missing_dependencies = set(step.depends_on) - step_id_set
            if missing_dependencies:
                raise ValueError(
                    f"{step.id} depends on missing steps: {sorted(missing_dependencies)}"
                )

            step_claim_ids = {claim.id for claim in step.claims}
            unknown_flags = set(step.human_review.flagged_claim_ids) - step_claim_ids
            unknown_edits = set(step.human_review.edited_claim_ids) - step_claim_ids
            if unknown_flags:
                raise ValueError(
                    f"{step.id} flags missing claims: {sorted(unknown_flags)}"
                )
            if unknown_edits:
                raise ValueError(
                    f"{step.id} edits missing claims: {sorted(unknown_edits)}"
                )

            for claim in step.claims:
                all_claim_ids.append(claim.id)
                missing_evidence = set(claim.evidence_ids) - set(evidence_map)
                if missing_evidence:
                    raise ValueError(
                        f"{claim.id} cites missing evidence: {sorted(missing_evidence)}"
                    )
                if (
                    claim.verification_status
                    in {
                        VerificationStatus.SUPPORTED,
                        VerificationStatus.PARTIALLY_SUPPORTED,
                    }
                    and not claim.evidence_ids
                ):
                    raise ValueError(
                        f"{claim.id} is {claim.verification_status.value} without evidence"
                    )

        if len(all_claim_ids) != len(set(all_claim_ids)):
            raise ValueError("claim IDs must be unique across the analysis run")

        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(step_id: str) -> None:
            if step_id in visiting:
                raise ValueError("analysis step dependency graph contains a cycle")
            if step_id in visited:
                return
            visiting.add(step_id)
            for dependency in graph.get(step_id, []):
                visit(dependency)
            visiting.remove(step_id)
            visited.add(step_id)

        for step_id in step_ids:
            visit(step_id)

        return self
