from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


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
    HUMAN_EDITED = "human_edited"
    APPROVED = "approved"
    NEEDS_REFRESH = "needs_refresh"


class HumanReviewStatus(str, Enum):
    NOT_REVIEWED = "not_reviewed"
    IN_REVIEW = "in_review"
    REVIEWED = "reviewed"
    APPROVED = "approved"


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
    version: str | None = None
    raw_text: str | None = None


class Evidence(StrictModel):
    id: str
    source_id: str
    snippet: str
    locator: str | None = None
    retrieved_at: datetime


class Claim(StrictModel):
    id: str
    text: str
    information_type: InformationType
    evidence_ids: list[str] = Field(default_factory=list)
    verification_status: VerificationStatus
    confidence: Confidence


class HumanReview(StrictModel):
    status: HumanReviewStatus = HumanReviewStatus.NOT_REVIEWED
    notes: list[str] = Field(default_factory=list)
    flagged_claim_ids: list[str] = Field(default_factory=list)
    edited_claim_ids: list[str] = Field(default_factory=list)


class AnalysisStep(StrictModel):
    id: str
    kind: str
    title: str
    status: StepStatus = StepStatus.DRAFT
    depends_on: list[str] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)
    ai_output: str | None = None
    human_review: HumanReview = Field(default_factory=HumanReview)
    version: int = Field(default=1, ge=1)


class AnalysisRun(StrictModel):
    schema_version: Literal["0.1.0"] = "0.1.0"
    id: str
    mode: AnalysisMode
    policy: Policy
    sources: list[Source] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    steps: list[AnalysisStep] = Field(default_factory=list)
    current_step_id: str | None = None
    final_review_status: HumanReviewStatus = HumanReviewStatus.NOT_REVIEWED
