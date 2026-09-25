from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from federal_register import NormalizedPolicyDocument, fetch_and_normalize
from foundry_client import FoundryChatClient, FoundryConfig
from guided_review import (
    begin_guided_review,
    clarify_current_step,
    edit_current_claim,
    flag_current_claim,
    next_guided_step,
    verify_current_claim,
)
from news_sources import NewsDiscovery, discover_news as discover_news_sources
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
    Source,
    StepKind,
    StepStatus,
    VerificationStatus,
)
from openai_client import OpenAIChatClient, OpenAIConfig
from openrouter_client import (
    DEFAULT_OPENROUTER_BASE_URL,
    DEFAULT_OPENROUTER_MODEL,
    OpenRouterChatClient,
    OpenRouterConfig,
)
from policy_interpreter import run_policy_interpreter
from policy_status import PolicyStatusSnapshot, fetch_policy_status
from response_sources import (
    CommentFetchError,
    CommentFetchReport,
    DEGRADED_ATTACHMENT_MARKER,
    fetch_comments_for_docket_with_report,
    is_attachment_placeholder,
    source_from_response_record,
)
from response_viewpoint_analyst import run_response_viewpoint_analyst
from revision_compare import (
    RevisionComparison,
    compare_documents,
    leadership_revision_summary,
    link_existing_claims,
    revision_audit_text,
)
from rush_mode import (
    approve_rush_final_review,
    combine_analysis_runs,
    open_rush_step_for_review,
    return_to_rush_final_review,
    run_rush_analysis,
)
from selective_reanalysis import (
    ReanalysisResult,
    build_evidence_audit_log,
    build_final_brief,
    mark_dependent_steps_needs_refresh,
    reanalyze_step,
    refresh_step,
)


ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "guide" / "full-stack"
HOST = "127.0.0.1"
PORT = 8777
ERROR_LOG_PATH = ROOT / ".policytrace" / "errors.jsonl"
_ERROR_LOG_LOCK = threading.Lock()
_STATE_WRITE_LOCK = threading.Lock()

POLICY_TEXT = (
    "Section 1 requires covered providers to maintain an annual compliance record. "
    "Section 2 requires licensed providers to submit an annual energy-use report by March 31."
)
RESPONSE_TEXT = (
    "One supplied commenter supports annual reporting because it creates a predictable schedule."
)


def _evidence(source: Source, evidence_id: str, snippet: str) -> Evidence:
    start = source.raw_text.index(snippet)
    return Evidence(
        id=evidence_id,
        source_id=source.id,
        snippet=snippet,
        start_offset=start,
        end_offset=start + len(snippet),
        retrieved_at=datetime(2026, 9, 23, tzinfo=timezone.utc),
    )


def _claim(
    claim_id: str,
    text: str,
    evidence_id: str,
    *,
    status: VerificationStatus = VerificationStatus.SUPPORTED,
) -> Claim:
    return Claim(
        id=claim_id,
        text=text,
        information_type=InformationType.AI_INTERPRETATION,
        evidence_ids=[evidence_id],
        verification_status=status,
        verification_note=(
            None
            if status == VerificationStatus.SUPPORTED
            else "Awaiting semantic verification in the full-stack guide."
        ),
        confidence="high",
    )


def make_guided_demo() -> AnalysisRun:
    source = Source(
        id="source-policy",
        title="[GUIDE DATA] Energy Reporting Rule",
        information_type=InformationType.OFFICIAL_POLICY,
        raw_text=POLICY_TEXT,
        pii_redaction_status=PiiRedactionStatus.NOT_APPLICABLE,
    )
    ev_record = _evidence(
        source,
        "evidence-record",
        "Section 1 requires covered providers to maintain an annual compliance record.",
    )
    ev_report = _evidence(
        source,
        "evidence-report",
        "Section 2 requires licensed providers to submit an annual energy-use report by March 31.",
    )

    steps = [
        AnalysisStep(
            id="step-policy-understanding",
            kind=StepKind.POLICY_UNDERSTANDING,
            title="Understand the policy",
            status=StepStatus.DRAFT,
            claims=[
                _claim(
                    "claim-understanding",
                    "The policy creates annual compliance recordkeeping and reporting duties.",
                    ev_record.id,
                    status=VerificationStatus.NEEDS_HUMAN_REVIEW,
                )
            ],
            ai_output="The policy creates annual compliance obligations for covered or licensed providers.",
            human_review=HumanReview(status=HumanReviewStatus.NOT_REVIEWED),
            version=1,
        ),
        AnalysisStep(
            id="step-major-provisions",
            kind=StepKind.MAJOR_PROVISIONS,
            title="Major provisions",
            status=StepStatus.DRAFT,
            depends_on=["step-policy-understanding"],
            claims=[
                _claim(
                    "claim-major",
                    "Licensed providers must submit an annual energy-use report by March 31.",
                    ev_report.id,
                    status=VerificationStatus.NEEDS_HUMAN_REVIEW,
                )
            ],
            ai_output="The clearest reporting deadline is March 31.",
            human_review=HumanReview(status=HumanReviewStatus.NOT_REVIEWED),
            version=1,
        ),
        AnalysisStep(
            id="step-stakeholders",
            kind=StepKind.STAKEHOLDERS,
            title="Stakeholders",
            status=StepStatus.DRAFT,
            depends_on=["step-major-provisions"],
            claims=[
                _claim(
                    "claim-stakeholders",
                    "Licensed providers are directly affected by the reporting requirement.",
                    ev_report.id,
                    status=VerificationStatus.NEEDS_HUMAN_REVIEW,
                )
            ],
            ai_output="Licensed providers are directly affected.",
            human_review=HumanReview(status=HumanReviewStatus.NOT_REVIEWED),
            version=1,
        ),
    ]

    return AnalysisRun(
        id="guide-guided-run",
        mode=AnalysisMode.GUIDED,
        policy=Policy(
            id="guide-policy",
            title="[GUIDE DATA] Energy Reporting Rule",
            jurisdiction="Demo / fictional",
            source_ids=[source.id],
        ),
        sources=[source],
        evidence=[ev_record, ev_report],
        steps=steps,
        current_step_id=None,
        final_review_status=HumanReviewStatus.NOT_REVIEWED,
    )


def make_rush_inputs() -> tuple[AnalysisRun, AnalysisRun]:
    policy_run = make_guided_demo()
    response_source = Source(
        id="source-response",
        title="[GUIDE DATA] Supplied public comment",
        information_type=InformationType.PUBLIC_OPINION,
        raw_text=RESPONSE_TEXT,
        pii_redaction_status=PiiRedactionStatus.NOT_DETECTED,
    )
    response_ev = _evidence(response_source, "evidence-response", RESPONSE_TEXT)
    response_step = AnalysisStep(
        id="step-public-response",
        kind=StepKind.PUBLIC_RESPONSE,
        title="Public response",
        claims=[
            _claim(
                "claim-response",
                "One supplied commenter supports annual reporting because it creates a predictable schedule.",
                response_ev.id,
                status=VerificationStatus.NEEDS_HUMAN_REVIEW,
            )
        ],
        ai_output="The supplied material includes one supportive response.",
        human_review=HumanReview(status=HumanReviewStatus.NOT_REVIEWED),
    )
    response_run = AnalysisRun(
        id="guide-response-run",
        mode=AnalysisMode.GUIDED,
        policy=Policy(
            id="guide-policy",
            title="[GUIDE DATA] Energy Reporting Rule",
            jurisdiction="Demo / fictional",
            source_ids=[],
        ),
        sources=[response_source],
        evidence=[response_ev],
        steps=[response_step],
        current_step_id=response_step.id,
        final_review_status=HumanReviewStatus.NOT_REVIEWED,
    )
    return policy_run, response_run


def _empty_response_analysis(policy_analysis: AnalysisRun) -> AnalysisRun:
    policy = policy_analysis.policy.model_copy(deep=True)
    policy.source_ids = []
    return AnalysisRun(
        id=f"empty-response-{policy_analysis.id}",
        mode=AnalysisMode.GUIDED,
        policy=policy,
        sources=[],
        evidence=[],
        steps=[],
        current_step_id=None,
        final_review_status=HumanReviewStatus.NOT_REVIEWED,
    )


def _guided_combined(
    policy_analysis: AnalysisRun,
    response_analysis: AnalysisRun,
) -> AnalysisRun:
    combined = combine_analysis_runs(policy_analysis, response_analysis)
    combined.mode = AnalysisMode.GUIDED
    combined.current_step_id = None
    combined.final_review_status = HumanReviewStatus.NOT_REVIEWED
    for step in combined.steps:
        step.human_review.status = HumanReviewStatus.NOT_REVIEWED
    return AnalysisRun.model_validate(combined.model_dump(mode="python"))


def deterministic_verifier(system_prompt: str, user_prompt: str) -> str:
    del system_prompt
    if "Claim ID:" not in user_prompt:
        raise ValueError("guide verifier expected a claim prompt")
    return json.dumps(
        {
            "status": "supported",
            "explanation": "Guide verifier: the cited passage directly supports this claim.",
            "narrower_wording": None,
        }
    )


class RuntimeProvider:
    """Local-process-only provider credentials. Secrets are never serialized."""

    def __init__(self) -> None:
        self.clear()

    def clear(self) -> None:
        self.kind = "deterministic"
        self.model = ""
        self.base_url = ""
        self.endpoint = ""
        self.api_key = ""
        self.bearer_token = ""
        self.regulations_api_key = ""
        self.media_cloud_api_key = ""

    def configure(self, data: dict[str, Any]) -> dict[str, Any]:
        kind = str(data.get("kind", "deterministic")).strip().lower()
        if kind not in {"deterministic", "openrouter", "openai", "foundry"}:
            raise ValueError("provider must be deterministic, openrouter, openai, or foundry")

        model = str(data.get("model", "")).strip()
        base_url = str(data.get("base_url", "")).strip()
        endpoint = str(data.get("endpoint", "")).strip()
        api_key = str(data.get("api_key", "")).strip()
        bearer_token = str(data.get("bearer_token", "")).strip()
        regulations_api_key = str(data.get("regulations_api_key", "")).strip()
        media_cloud_api_key = str(data.get("media_cloud_api_key", "")).strip()

        if kind == "openrouter":
            if not api_key:
                raise ValueError("OpenRouter API key is required")
            if not model:
                model = DEFAULT_OPENROUTER_MODEL
            if not base_url:
                base_url = DEFAULT_OPENROUTER_BASE_URL
        elif kind == "openai":
            if not api_key:
                raise ValueError("OpenAI API key is required")
            if not model:
                raise ValueError("OpenAI model is required")
        elif kind == "foundry":
            if not endpoint:
                raise ValueError("Foundry endpoint is required")
            if not model:
                raise ValueError("Foundry model is required")
            if bool(api_key) == bool(bearer_token):
                raise ValueError("Foundry requires exactly one API key or bearer token")

        # Commit the new provider configuration only after every check passes.
        # A typo or blank credential must not destroy a working in-memory setup.
        self.kind = kind
        self.model = model
        self.base_url = base_url
        self.endpoint = endpoint
        self.api_key = api_key
        self.bearer_token = bearer_token
        self.regulations_api_key = regulations_api_key
        self.media_cloud_api_key = media_cloud_api_key

        return self.status()

    def status(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "model": self.model,
            "base_url": self.base_url,
            "endpoint": self.endpoint,
            "has_api_key": bool(self.api_key),
            "has_bearer_token": bool(self.bearer_token),
            "has_regulations_api_key": bool(self.regulations_api_key),
            "has_media_cloud_api_key": bool(self.media_cloud_api_key),
            "credentials_storage": "process_memory_only",
            "regulations_note": (
                "Used only by the local live-comment ingestion route and kept "
                "in process memory."
            ),
            "media_cloud_note": (
                "Optional. Used only for historical factual-reporting discovery "
                "and kept in process memory."
            ),
        }

    def model_call(self) -> Callable[[str, str], str]:
        if self.kind == "deterministic":
            return deterministic_verifier
        if self.kind == "openrouter":
            client = OpenRouterChatClient(
                OpenRouterConfig(
                    api_key=self.api_key,
                    model=self.model or DEFAULT_OPENROUTER_MODEL,
                    base_url=self.base_url or DEFAULT_OPENROUTER_BASE_URL,
                )
            )
            return client.complete_json
        if self.kind == "openai":
            client = OpenAIChatClient(
                OpenAIConfig(
                    api_key=self.api_key,
                    model=self.model,
                    base_url=self.base_url or "https://api.openai.com/v1",
                )
            )
            return client.complete_json

        client = FoundryChatClient(
            FoundryConfig(
                endpoint=self.endpoint,
                model=self.model,
                api_key=self.api_key or None,
                bearer_token=self.bearer_token or None,
            )
        )
        return client.complete_json


NEWS_REVIEW_STEP_ID = "step-related-media"


def _news_claim_id(source: Source) -> str:
    suffix = source.id.removeprefix("source-")
    return f"claim-news-{suffix}"


def _news_review_materials(
    discovery: NewsDiscovery,
) -> tuple[list[Source], list[Evidence], AnalysisStep]:
    sources = [source.model_copy(deep=True) for source in discovery.sources]
    evidence: list[Evidence] = []
    claims: list[Claim] = []

    for source in sources:
        title = (source.title or "").strip()
        if not title:
            continue
        suffix = source.id.removeprefix("source-")
        evidence_id = f"evidence-news-{suffix}"
        claim_id = _news_claim_id(source)
        evidence.append(
            Evidence(
                id=evidence_id,
                source_id=source.id,
                snippet=title,
                locator="News discovery headline/title only",
                start_offset=0,
                end_offset=len(title),
                retrieved_at=discovery.checked_at,
            )
        )
        claims.append(
            Claim(
                id=claim_id,
                text=title,
                information_type=InformationType.FACTUAL_REPORTING,
                evidence_ids=[evidence_id],
                verification_status=VerificationStatus.SUPPORTED,
                verification_note=(
                    "Discovery-only source pointer. The cited evidence is the "
                    "provider-supplied headline/title; article-body factual content "
                    "was not ingested or verified."
                ),
                confidence="medium",
            )
        )

    step = AnalysisStep(
        id=NEWS_REVIEW_STEP_ID,
        kind=StepKind.FACTUAL_REPORTING,
        title="Related media / factual reporting",
        status=StepStatus.DRAFT,
        claims=claims,
        ai_output=(
            "Review the discovered media/source pointers. Headlines and metadata "
            "are discovery evidence only, not verified article-body facts."
        ),
        human_review=HumanReview(status=HumanReviewStatus.NOT_REVIEWED),
        version=1,
    )
    return sources, evidence, step


class GuideState:
    def __init__(self) -> None:
        self.analysis = make_guided_demo()
        self.provider = RuntimeProvider()
        self.document: NormalizedPolicyDocument | None = None
        self.policy_analysis: AnalysisRun | None = None
        self.response_analysis: AnalysisRun | None = None
        self.last_comment_fetch_report: CommentFetchReport | None = None
        self.policy_status: PolicyStatusSnapshot | None = None
        self.revision_comparison: RevisionComparison | None = None
        self.news_discovery: NewsDiscovery | None = None

    def _sync_news_review_step(self, analysis: AnalysisRun) -> AnalysisRun:
        updated = AnalysisRun.model_validate(analysis.model_dump(mode="python"))
        existing = next(
            (step for step in updated.steps if step.id == NEWS_REVIEW_STEP_ID),
            None,
        )
        if existing is None:
            existing = next(
                (
                    step
                    for step in self.analysis.steps
                    if step.id == NEWS_REVIEW_STEP_ID
                ),
                None,
            )

        old_evidence_ids = {
            evidence_id
            for claim in (existing.claims if existing else [])
            for evidence_id in claim.evidence_ids
        }
        old_source_ids = {
            evidence.source_id
            for evidence in updated.evidence
            if evidence.id in old_evidence_ids
        }

        updated.steps = [
            step
            for step in updated.steps
            if step.id != NEWS_REVIEW_STEP_ID
            and step.kind != StepKind.DRAFT_BRIEF
        ]
        updated.evidence = [
            evidence
            for evidence in updated.evidence
            if evidence.id not in old_evidence_ids
        ]
        referenced_source_ids = {evidence.source_id for evidence in updated.evidence}
        updated.sources = [
            source
            for source in updated.sources
            if source.id not in old_source_ids or source.id in referenced_source_ids
        ]

        discovery = self.news_discovery
        if discovery is None or not discovery.sources:
            return AnalysisRun.model_validate(updated.model_dump(mode="python"))

        news_sources, news_evidence, news_step = _news_review_materials(discovery)
        existing_claim_ids = (
            {claim.id for claim in existing.claims}
            if existing is not None
            else set()
        )
        new_claim_ids = {claim.id for claim in news_step.claims}
        if existing is not None and existing_claim_ids == new_claim_ids:
            news_step.human_review = existing.human_review.model_copy(deep=True)
            news_step.status = existing.status
            news_step.version = existing.version
        elif existing is not None:
            news_step.version = existing.version + 1
            news_step.human_review.excluded_claim_ids = [
                claim_id
                for claim_id in existing.human_review.excluded_claim_ids
                if claim_id in new_claim_ids
            ]

        content_steps = [
            step
            for step in updated.steps
            if step.kind not in {StepKind.VERIFICATION, StepKind.DRAFT_BRIEF}
        ]
        if content_steps:
            news_step.depends_on = [content_steps[-1].id]

        source_ids = {source.id for source in updated.sources}
        for source in news_sources:
            if source.id not in source_ids:
                updated.sources.append(source)
                source_ids.add(source.id)
        updated.evidence.extend(news_evidence)

        verification_index = next(
            (
                index
                for index, step in enumerate(updated.steps)
                if step.kind == StepKind.VERIFICATION
            ),
            len(updated.steps),
        )
        updated.steps.insert(verification_index, news_step)

        if existing is None or existing_claim_ids != new_claim_ids:
            if updated.final_review_status == HumanReviewStatus.APPROVED:
                updated.final_review_status = HumanReviewStatus.IN_REVIEW

        return AnalysisRun.model_validate(updated.model_dump(mode="python"))

    def _require_live_model(self) -> None:
        if self.provider.kind == "deterministic":
            raise ValueError(
                "Live source analysis requires OpenRouter, OpenAI, or Microsoft Foundry. "
                "Configure a provider first, or keep using the fictional demo."
            )

    def _guided_loaded_analysis(self) -> AnalysisRun:
        if self.policy_analysis is None:
            loaded = make_guided_demo()
        elif self.response_analysis is None:
            loaded = AnalysisRun.model_validate(
                self.policy_analysis.model_dump(mode="python")
            )
            loaded.mode = AnalysisMode.GUIDED
            loaded.current_step_id = None
            loaded.final_review_status = HumanReviewStatus.NOT_REVIEWED
            for step in loaded.steps:
                step.human_review.status = HumanReviewStatus.NOT_REVIEWED
        else:
            loaded = _guided_combined(self.policy_analysis, self.response_analysis)
        return self._sync_news_review_step(loaded)

    def reset(self, mode: str = "guided") -> AnalysisRun:
        if mode == "rush":
            return self.run_rush()
        self.analysis = self._guided_loaded_analysis()
        return self.analysis

    def load_policy(self, document_number: str) -> AnalysisRun:
        document_number = document_number.strip()
        if not document_number:
            raise ValueError("Federal Register document number is required")
        self._require_live_model()

        try:
            document = fetch_and_normalize(document_number)
        except Exception as exc:
            raise RuntimeError(
                f"Could not load Federal Register document {document_number}: {exc}"
            ) from exc

        analysis = run_policy_interpreter(
            document,
            self.provider.model_call(),
            mode=AnalysisMode.GUIDED,
        )
        status = fetch_policy_status(document)
        self.document = document
        self.policy_analysis = analysis
        self.response_analysis = None
        self.last_comment_fetch_report = None
        self.policy_status = status
        self.revision_comparison = None
        self.news_discovery = None
        self.analysis = AnalysisRun.model_validate(
            analysis.model_dump(mode="python")
        )
        self.analysis.current_step_id = None
        return AnalysisRun.model_validate(self.analysis.model_dump(mode="python"))

    def discover_news(
        self,
        *,
        query: str = "",
        max_articles: int = 8,
    ) -> dict[str, Any]:
        if self.document is None:
            raise ValueError("Load a Federal Register policy before finding related news")

        discovery = discover_news_sources(
            policy_title=self.document.title,
            publication_date=self.document.publication_date,
            query=query or None,
            max_articles=max_articles,
            media_cloud_api_key=self.provider.media_cloud_api_key,
        )

        self.news_discovery = discovery
        self.analysis = self._sync_news_review_step(self.analysis)
        return self.news_status_payload()

    def news_status_payload(self) -> dict[str, Any]:
        discovery = self.news_discovery
        if discovery is None:
            return {"available": False, "sources": []}
        return {
            "available": True,
            **discovery.model_dump(mode="json"),
        }

    def set_news_article_use(
        self,
        claim_id: str,
        *,
        use: bool,
    ) -> AnalysisRun:
        claim_id = claim_id.strip()
        media_step = next(
            (
                step
                for step in self.analysis.steps
                if step.id == NEWS_REVIEW_STEP_ID
            ),
            None,
        )
        if media_step is None:
            raise ValueError("No related media section is available")
        if claim_id not in {claim.id for claim in media_step.claims}:
            raise ValueError(f"unknown media source pointer {claim_id!r}")

        excluded = media_step.human_review.excluded_claim_ids
        if use:
            if claim_id in excluded:
                excluded.remove(claim_id)
        elif claim_id not in excluded:
            excluded.append(claim_id)

        media_step.human_review.status = HumanReviewStatus.IN_REVIEW
        self.analysis.steps = [
            step
            for step in self.analysis.steps
            if step.kind != StepKind.DRAFT_BRIEF
        ]
        self.analysis.current_step_id = media_step.id
        if self.analysis.final_review_status == HumanReviewStatus.APPROVED:
            self.analysis.final_review_status = HumanReviewStatus.IN_REVIEW
        self.analysis = AnalysisRun.model_validate(
            self.analysis.model_dump(mode="python")
        )
        return self.analysis

    def _excluded_news_claim_ids(self) -> set[str]:
        media_step = next(
            (
                step
                for step in self.analysis.steps
                if step.id == NEWS_REVIEW_STEP_ID
            ),
            None,
        )
        if media_step is None:
            return set()
        return set(media_step.human_review.excluded_claim_ids)

    def _news_brief_text(self) -> str | None:
        discovery = self.news_discovery
        if discovery is None:
            return None

        excluded = self._excluded_news_claim_ids()
        selected_sources = [
            source
            for source in discovery.sources
            if _news_claim_id(source) not in excluded
        ]
        lines = [
            "## Related factual reporting",
            f"- Discovery provider: {discovery.provider}",
            f"- Query: {discovery.query}",
            f"- Articles discovered: {len(discovery.sources)}",
            f"- Articles selected for report: {len(selected_sources)}",
            f"- Limitation: {discovery.limitation}",
        ]
        for attempt in discovery.provider_attempts:
            window = ""
            if attempt.window_start or attempt.window_end:
                window = (
                    f" | window: {attempt.window_start or 'open'} to "
                    f"{attempt.window_end or 'open'}"
                )
            lines.append(
                f"- Provider attempt: {attempt.provider} [{attempt.status}] "
                f"{attempt.detail}{window}"
            )
        if discovery.window_start or discovery.window_end:
            lines.append(
                "- Search window: "
                f"{discovery.window_start or 'open'} to "
                f"{discovery.window_end or 'open'}"
            )
        for source in selected_sources[:8]:
            parts = [source.title]
            if source.agency:
                parts.append(source.agency)
            if source.published_at:
                parts.append(source.published_at.isoformat())
            line = " — ".join(parts)
            # Keep leadership output readable and printable. Full source URLs,
            # including opaque Google News RSS redirect URLs, remain in the
            # evidence audit log and interactive UI.
            lines.append(f"- [factual_reporting] {line}")
        if len(selected_sources) > 8:
            lines.append(
                f"- {len(selected_sources) - 8} additional selected source(s) "
                "are preserved in the Evidence Audit Log."
            )
        if not selected_sources:
            lines.append("- No discovered media sources were selected for this report.")
        return "\n".join(lines)

    def _news_audit_text(self) -> str | None:
        discovery = self.news_discovery
        if discovery is None:
            return None

        excluded = self._excluded_news_claim_ids()
        lines = [
            "## Factual reporting source audit",
            f"- Provider: {discovery.provider}",
            f"- Query: {discovery.query}",
            f"- Checked at: {discovery.checked_at.isoformat()}",
            f"- Limitation: {discovery.limitation}",
        ]
        for attempt in discovery.provider_attempts:
            window = ""
            if attempt.window_start or attempt.window_end:
                window = (
                    f" | window: {attempt.window_start or 'open'} to "
                    f"{attempt.window_end or 'open'}"
                )
            lines.append(
                f"- Provider attempt: {attempt.provider} [{attempt.status}] "
                f"{attempt.detail}{window}"
            )
        for source in discovery.sources:
            lines.extend(
                [
                    "",
                    f"### {source.id}",
                    "- Information type: factual_reporting",
                    f"- Title: {source.title}",
                    f"- Publisher/domain: {source.agency or 'unknown'}",
                    (
                        "- Reviewer selection: "
                        + (
                            "EXCLUDED BY REVIEWER"
                            if _news_claim_id(source) in excluded
                            else "USED IN REPORT"
                        )
                    ),
                    (
                        "- Published: "
                        + (
                            source.published_at.isoformat()
                            if source.published_at
                            else "unknown"
                        )
                    ),
                    f"- URL: {source.url or 'unavailable'}",
                    "- Stored discovery text: headline/title only",
                ]
            )
        return "\n".join(lines)

    def compare_revision(self, document_number: str) -> dict[str, Any]:
        if self.document is None:
            raise ValueError("Load a Federal Register policy before comparing revisions")

        document_number = document_number.strip()
        if not document_number:
            raise ValueError("A second Federal Register document number is required")
        if document_number == self.document.document_number:
            raise ValueError("Choose a different Federal Register document to compare")

        try:
            other_document = fetch_and_normalize(document_number)
        except Exception as exc:
            raise RuntimeError(
                f"Could not load comparison Federal Register document "
                f"{document_number}: {exc}"
            ) from exc

        comparison = compare_documents(self.document, other_document)
        self.revision_comparison = comparison
        return self.revision_comparison_payload()

    def revision_comparison_payload(self) -> dict[str, Any]:
        if self.revision_comparison is None or self.document is None:
            return {"available": False}

        linked = link_existing_claims(
            self.revision_comparison,
            self.analysis,
            analyzed_document_number=self.document.document_number,
        )
        return {
            "available": True,
            **linked.model_dump(mode="json"),
        }

    def _revision_brief_text(self) -> str | None:
        if self.revision_comparison is None or self.document is None:
            return None
        linked = link_existing_claims(
            self.revision_comparison,
            self.analysis,
            analyzed_document_number=self.document.document_number,
        )
        return leadership_revision_summary(linked)

    def _revision_audit_text(self) -> str | None:
        if self.revision_comparison is None or self.document is None:
            return None
        linked = link_existing_claims(
            self.revision_comparison,
            self.analysis,
            analyzed_document_number=self.document.document_number,
        )
        return revision_audit_text(linked)

    def load_comments(
        self,
        docket_id: str,
        *,
        max_comments: int = 12,
    ) -> AnalysisRun:
        docket_id = docket_id.strip()
        if not docket_id:
            raise ValueError("Regulations.gov docket ID is required")
        if self.document is None or self.policy_analysis is None:
            raise ValueError("Load a Federal Register policy before loading comments")
        if not self.provider.regulations_api_key:
            raise ValueError(
                "A Regulations.gov API key is required to load live comments"
            )
        if max_comments < 1 or max_comments > 100:
            raise ValueError("max_comments must be between 1 and 100")
        self._require_live_model()

        self.last_comment_fetch_report = None
        try:
            fetched = fetch_comments_for_docket_with_report(
                docket_id,
                api_key=self.provider.regulations_api_key,
                max_comments=max_comments,
            )
            self.last_comment_fetch_report = fetched.report
            records = fetched.records
        except CommentFetchError as exc:
            self.last_comment_fetch_report = exc.report
            raise RuntimeError(
                f"Could not load Regulations.gov docket {docket_id}: {exc}"
            ) from exc
        except Exception as exc:
            raise RuntimeError(
                f"Could not load Regulations.gov docket {docket_id}: {exc}"
            ) from exc
        if not records:
            raise ValueError(
                f"No usable Regulations.gov comments were returned for {docket_id}"
            )

        response_sources = [
            source_from_response_record(record)
            for record in records
        ]
        response_analysis = run_response_viewpoint_analyst(
            self.document,
            response_sources,
            self.provider.model_call(),
            mode=AnalysisMode.GUIDED,
        )
        self.response_analysis = response_analysis
        self.analysis = self._sync_news_review_step(
            _guided_combined(
                self.policy_analysis,
                response_analysis,
            )
        )
        return self.analysis

    def policy_status_payload(self) -> dict[str, Any]:
        document = self.document
        status = self.policy_status
        return {
            "available": bool(status and status.available),
            "document_number": (
                None if document is None else document.document_number
            ),
            "document_type": (
                None if document is None else document.document_type
            ),
            "source_publication_date": (
                None
                if document is None or document.publication_date is None
                else document.publication_date.isoformat()
            ),
            "rin": None if status is None else status.rin,
            "checked_at": (
                None
                if status is None
                else status.checked_at.isoformat()
            ),
            "source_name": (
                None if status is None else status.source_name
            ),
            "source_url": (
                None if status is None else status.source_url
            ),
            "agenda_stage": (
                None if status is None else status.agenda_stage
            ),
            "rin_status": (
                None if status is None else status.rin_status
            ),
            "status_label": (
                "Not checked"
                if status is None
                else status.status_label
            ),
            "latest_completed_action": (
                None
                if status is None or status.latest_completed_action is None
                else status.latest_completed_action.model_dump(mode="json")
            ),
            "federal_register_documents": (
                []
                if status is None
                else [
                    item.model_dump(mode="json")
                    for item in status.federal_register_documents
                ]
            ),
            "later_federal_register_documents": (
                []
                if status is None
                else [
                    item.model_dump(mode="json")
                    for item in status.later_federal_register_documents
                ]
            ),
            "federal_register_check_error": (
                None
                if status is None
                else status.federal_register_check_error
            ),
            "later_material_action_found": (
                False
                if status is None
                else status.later_material_action_found
            ),
            "freshness_message": (
                "Current status has not been checked yet."
                if status is None
                else status.freshness_message
            ),
            "error": None if status is None else status.error,
        }

    def _policy_status_brief_text(self) -> str | None:
        status = self.policy_status_payload()
        if self.document is None:
            return None

        lines = [
            "## Current status / freshness",
            f"- Source document: {self.document.document_number}",
            f"- Document type: {self.document.document_type or 'unknown'}",
            (
                "- Source publication date: "
                + (
                    self.document.publication_date.isoformat()
                    if self.document.publication_date
                    else "unknown"
                )
            ),
            f"- RIN: {status['rin'] or 'not available'}",
            f"- Current status check: {status['status_label']}",
            (
                "- Federal Register documents for this RIN: "
                f"{len(status['federal_register_documents'])}"
            ),
            (
                "- Later Federal Register documents after this source: "
                f"{len(status['later_federal_register_documents'])}"
            ),
            f"- Checked at: {status['checked_at'] or 'not checked'}",
            f"- Freshness note: {status['freshness_message']}",
        ]
        for item in status["later_federal_register_documents"][:5]:
            lines.append(
                "- Later Federal Register document: "
                f"{item.get('document_number')} "
                f"({item.get('publication_date') or 'date unknown'}) — "
                f"{item.get('title')}"
            )
        if status["source_url"]:
            lines.append(f"- Status source: {status['source_url']}")
        return "\n".join(lines)

    def comment_corpus_status(self) -> dict[str, Any]:
        report = self.last_comment_fetch_report
        response_sources = (
            []
            if self.response_analysis is None
            else [
                source
                for source in self.response_analysis.sources
                if source.information_type
                in {
                    InformationType.PUBLIC_OPINION,
                    InformationType.STAKEHOLDER_CLAIM,
                    InformationType.FACTUAL_REPORTING,
                }
            ]
        )
        usable_sources = [
            source
            for source in response_sources
            if source.raw_text and not is_attachment_placeholder(source.raw_text)
        ]
        cluster_ids = {
            source.duplicate_cluster_id or source.id
            for source in usable_sources
        }
        source_type_counts: dict[str, int] = {}
        for source in usable_sources:
            key = source.information_type.value
            source_type_counts[key] = source_type_counts.get(key, 0) + 1

        failures = [] if report is None else [
            failure.model_dump(mode="json") for failure in report.failures
        ]
        retrieved_count = (
            len(response_sources)
            if report is None
            else report.retrieved_count
        )
        unusable_count = (
            len(response_sources) - len(usable_sources)
            if report is None
            else report.unusable_count
        )

        return {
            "available": bool(report or response_sources),
            "docket_id": None if report is None else report.docket_id,
            "requested_count": None if report is None else report.requested_count,
            "source_document_count": (
                None if report is None else report.source_document_count
            ),
            "observed_candidate_count": (
                None if report is None else report.observed_candidate_count
            ),
            "attempted_count": None if report is None else report.attempted_count,
            "retrieved_count": retrieved_count,
            "failed_retrieval_count": len(failures),
            "unusable_retrieval_count": unusable_count,
            "failures": failures,
            "analyzed_source_count": len(usable_sources),
            "exact_text_cluster_count": len(cluster_ids),
            "source_type_counts": source_type_counts,
            "pii_redacted_count": sum(
                source.pii_redaction_status == PiiRedactionStatus.REDACTED
                for source in usable_sources
            ),
            "degraded_source_count": sum(
                DEGRADED_ATTACHMENT_MARKER in (source.raw_text or "")
                for source in usable_sources
            ),
            "degraded_attachment_count": sum(
                (source.raw_text or "").count(DEGRADED_ATTACHMENT_MARKER)
                for source in usable_sources
            ),
            "representativeness_warning": (
                "These materials are not a representative sample of the general "
                "public and must not be generalized to population-wide opinion."
            ),
        }

    def _corpus_brief_text(self) -> str | None:
        status = self.comment_corpus_status()
        if not status["available"]:
            return None

        requested = status["requested_count"]
        requested_text = "unknown" if requested is None else str(requested)
        source_types = ", ".join(
            f"{key}={value}"
            for key, value in sorted(status["source_type_counts"].items())
        ) or "none"

        lines = [
            "## Corpus limits",
            f"- Requested up to: {requested_text} comments",
            f"- Retrieved: {status['retrieved_count']}",
            f"- Analyzed source records: {status['analyzed_source_count']}",
            f"- Exact-text clusters: {status['exact_text_cluster_count']}",
            f"- Retrieval failures: {status['failed_retrieval_count']}",
            f"- Unusable retrieved records: {status['unusable_retrieval_count']}",
            f"- PII-pattern redactions: {status['pii_redacted_count']} source records",
            f"- Degraded source records: {status['degraded_source_count']}",
            f"- Degraded attachments: {status['degraded_attachment_count']}",
            f"- Source types: {source_types}",
            f"- Limitation: {status['representativeness_warning']}",
        ]
        return "\n".join(lines)

    def guided_begin(self, step_id: str | None = None) -> AnalysisRun:
        self.analysis = begin_guided_review(self.analysis, step_id=step_id)
        return self.analysis

    def guided_clarify(self, note: str) -> AnalysisRun:
        self.analysis = clarify_current_step(self.analysis, note)
        return self.analysis

    def guided_edit(self, claim_id: str, text: str) -> AnalysisRun:
        step_id = self.analysis.current_step_id
        if step_id is None:
            raise ValueError("guided review has no current step")

        edited = edit_current_claim(self.analysis, claim_id, text)
        self.analysis = mark_dependent_steps_needs_refresh(edited, step_id)
        return self.analysis

    def guided_flag(self, claim_id: str, note: str | None) -> AnalysisRun:
        self.analysis = flag_current_claim(self.analysis, claim_id, note)
        return self.analysis

    def guided_verify(self, claim_id: str) -> AnalysisRun:
        self.analysis = verify_current_claim(
            self.analysis,
            claim_id,
            self.provider.model_call(),
        )
        return self.analysis

    def guided_next(self) -> AnalysisRun:
        self.analysis = next_guided_step(self.analysis)
        return self.analysis

    def run_rush(self) -> AnalysisRun:
        if self.policy_analysis is None:
            policy_run, response_run = make_rush_inputs()
        else:
            policy_run = self.policy_analysis
            response_run = (
                self.response_analysis
                if self.response_analysis is not None
                else _empty_response_analysis(policy_run)
            )
        self.analysis = self._sync_news_review_step(
            run_rush_analysis(
                policy_run,
                response_run,
                self.provider.model_call(),
            )
        )
        return self.analysis

    def rush_open(self, step_id: str) -> AnalysisRun:
        self.analysis = open_rush_step_for_review(self.analysis, step_id)
        return self.analysis

    def rush_final(self) -> AnalysisRun:
        self.analysis = return_to_rush_final_review(self.analysis)
        return self.analysis

    def rush_approve(
        self,
        acknowledge_unreviewed: bool = False,
        acknowledge_flags: bool = False,
    ) -> AnalysisRun:
        self.analysis = approve_rush_final_review(
            self.analysis,
            acknowledge_unreviewed=acknowledge_unreviewed,
            acknowledge_flags=acknowledge_flags,
        )
        return self.analysis

    def reanalyze(
        self,
        step_id: str,
        text: str,
        *,
        claim_id: str | None = None,
        human_edited: bool = True,
    ) -> AnalysisRun:
        replacement_text = text.strip()
        if not replacement_text:
            raise ValueError("replacement claim text must not be empty")

        requested_claim_id = (claim_id or "").strip()

        def regenerate(snapshot: AnalysisRun, selected: AnalysisStep) -> ReanalysisResult:
            del snapshot
            replacement = selected.model_copy(deep=True)
            if not replacement.claims:
                raise ValueError("selected guide step has no claims")

            if requested_claim_id:
                target = next(
                    (
                        claim
                        for claim in replacement.claims
                        if claim.id == requested_claim_id
                    ),
                    None,
                )
                if target is None:
                    raise ValueError(
                        f"claim {requested_claim_id!r} is not part of step {step_id!r}"
                    )
            elif len(replacement.claims) == 1:
                # Preserve compatibility with the reviewer harness and older
                # one-claim callers while avoiding ambiguous edits.
                target = replacement.claims[0]
            else:
                raise ValueError(
                    "claim_id is required when re-analyzing a step with multiple claims"
                )

            target.text = replacement_text
            target.verification_status = VerificationStatus.NEEDS_HUMAN_REVIEW
            target.verification_note = (
                "Guide re-analysis changed this claim; re-verification is required."
            )
            edited = (target.id,) if human_edited else ()
            return ReanalysisResult(
                step=replacement,
                human_edited_claim_ids=edited,
            )

        self.analysis = reanalyze_step(self.analysis, step_id, regenerate)
        return self.analysis

    def refresh(self, step_id: str) -> AnalysisRun:
        def regenerate(snapshot: AnalysisRun, selected: AnalysisStep) -> ReanalysisResult:
            del snapshot
            replacement = selected.model_copy(deep=True)
            replacement.ai_output = (
                (replacement.ai_output or replacement.title)
                + " [refreshed from current dependencies]"
            )
            for claim in replacement.claims:
                claim.verification_status = VerificationStatus.NEEDS_HUMAN_REVIEW
                claim.verification_note = (
                    "Guide refresh changed this section; re-verification is required."
                )
            return ReanalysisResult(step=replacement)

        self.analysis = refresh_step(self.analysis, step_id, regenerate)
        return self.analysis

    def review_reanalysis(self, step_id: str) -> AnalysisRun:
        step = next((item for item in self.analysis.steps if item.id == step_id), None)
        if step is None:
            raise ValueError(f"unknown analysis step {step_id!r}")
        if step.status == StepStatus.NEEDS_REFRESH:
            raise ValueError("refresh this step before marking it reviewed")

        original_mode = self.analysis.mode
        for claim in step.claims:
            if claim.verification_status == VerificationStatus.NEEDS_HUMAN_REVIEW:
                if original_mode == AnalysisMode.RUSH:
                    checked = open_rush_step_for_review(self.analysis, step.id)
                else:
                    checked = begin_guided_review(self.analysis, step_id=step.id)
                self.analysis = verify_current_claim(
                    checked,
                    claim.id,
                    self.provider.model_call(),
                )
                step = next(item for item in self.analysis.steps if item.id == step_id)

        step.status = StepStatus.VERIFIED
        step.human_review.status = HumanReviewStatus.REVIEWED
        self.analysis.mode = original_mode
        self.analysis = AnalysisRun.model_validate(self.analysis.model_dump(mode="python"))
        return self.analysis

    def brief(self) -> AnalysisRun:
        self.analysis = build_final_brief(self.analysis)
        brief = next(
            step
            for step in self.analysis.steps
            if step.kind == StepKind.DRAFT_BRIEF
        )

        additions = [
            value
            for value in (
                self._policy_status_brief_text(),
                self._revision_brief_text(),
                self._corpus_brief_text(),
                self._news_brief_text(),
            )
            if value
        ]
        if additions:
            brief.ai_output = (
                (brief.ai_output or "").rstrip()
                + "\n\n"
                + "\n\n".join(additions)
            )
            self.analysis = AnalysisRun.model_validate(
                self.analysis.model_dump(mode="python")
            )
        return self.analysis

    def evidence_audit_log(self) -> str:
        text = build_evidence_audit_log(self.analysis)
        additions = [
            value
            for value in (
                self._policy_status_brief_text(),
                self._revision_audit_text(),
                self._corpus_brief_text(),
                self._news_audit_text(),
            )
            if value
        ]
        if additions:
            text = text.rstrip() + "\n\n" + "\n\n".join(additions)
        return text

    def approve_final_brief(
        self,
        *,
        acknowledge_flags: bool = False,
    ) -> AnalysisRun:
        reviewed = AnalysisRun.model_validate(self.analysis.model_dump(mode="python"))
        if reviewed.final_review_status != HumanReviewStatus.IN_REVIEW:
            raise ValueError("final brief is not awaiting human approval")

        stale = [
            step.id
            for step in reviewed.steps
            if step.status == StepStatus.NEEDS_REFRESH
            and step.kind not in {StepKind.VERIFICATION, StepKind.DRAFT_BRIEF}
        ]
        if stale:
            raise ValueError(
                "cannot approve final brief while steps need refresh: "
                f"{sorted(stale)}"
            )

        content_steps = [
            step
            for step in reviewed.steps
            if step.kind not in {StepKind.VERIFICATION, StepKind.DRAFT_BRIEF}
        ]
        outstanding = [
            step.id
            for step in content_steps
            if step.human_review.status
            not in {HumanReviewStatus.REVIEWED, HumanReviewStatus.APPROVED}
        ]
        if outstanding:
            raise ValueError(
                "cannot approve final brief while sections are unreviewed: "
                f"{sorted(outstanding)}"
            )

        brief = next(
            (step for step in reviewed.steps if step.kind == StepKind.DRAFT_BRIEF),
            None,
        )
        if brief is None:
            raise ValueError("build the final brief before approving it")

        unresolved_flags = [
            (step, claim_id)
            for step in content_steps
            for claim_id in step.human_review.flagged_claim_ids
        ]
        if unresolved_flags and not acknowledge_flags:
            labels = [
                f"{step.id}:{claim_id}"
                for step, claim_id in unresolved_flags
            ]
            raise ValueError(
                "cannot approve final brief while reviewer flags are unresolved: "
                f"{sorted(labels)}. Resolve the finding or approve with "
                "acknowledge_flags=True to record the override."
            )

        if unresolved_flags:
            for step, claim_id in unresolved_flags:
                override = (
                    f"Final approval acknowledged unresolved reviewer flag "
                    f"{claim_id} (acknowledged override)."
                )
                if override not in step.human_review.notes:
                    step.human_review.notes.append(override)
            brief.human_review.notes.append(
                f"Final brief approved with {len(unresolved_flags)} unresolved "
                "reviewer flag(s) (acknowledged override)."
            )

        brief.status = StepStatus.VERIFIED
        brief.human_review.status = HumanReviewStatus.APPROVED
        reviewed.current_step_id = None
        reviewed.final_review_status = HumanReviewStatus.APPROVED
        self.analysis = AnalysisRun.model_validate(reviewed.model_dump(mode="python"))
        return self.analysis


STATE = GuideState()


def _safe_error_message(message: object) -> str:
    safe = str(message)
    secrets = (
        STATE.provider.api_key,
        STATE.provider.bearer_token,
        STATE.provider.regulations_api_key,
    )
    for secret in secrets:
        if secret:
            safe = safe.replace(secret, "[REDACTED]")
    return safe[:4000]


def _record_error(
    *,
    method: str,
    path: str,
    status: int,
    message: object,
    error_type: str,
) -> tuple[str, str]:
    now = datetime.now(timezone.utc)
    error_id = (
        f"ERR-{now.strftime('%Y%m%d-%H%M%S')}-"
        f"{uuid4().hex[:8].upper()}"
    )
    safe_message = _safe_error_message(message)
    entry = {
        "error_id": error_id,
        "timestamp": now.isoformat(),
        "method": method,
        "path": path.split("?", 1)[0],
        "status": status,
        "error_type": error_type,
        "message": safe_message,
        "mode": STATE.analysis.mode.value,
        "current_step_id": STATE.analysis.current_step_id,
        "provider_kind": STATE.provider.kind,
    }

    ERROR_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _ERROR_LOG_LOCK:
        with ERROR_LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")

    print(
        f"[POLICYTRACE ERROR {error_id}] "
        f"{method} {entry['path']} -> {status}: {safe_message}"
    )
    return error_id, safe_message


def _recent_errors(limit: int = 50) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit), 100))
    if not ERROR_LOG_PATH.exists():
        return []

    with _ERROR_LOG_LOCK:
        lines = ERROR_LOG_PATH.read_text(encoding="utf-8").splitlines()

    entries: list[dict[str, Any]] = []
    for line in lines[-limit:]:
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            entries.append(value)
    return entries


def _json_bytes(payload: Any) -> bytes:
    if isinstance(payload, AnalysisRun):
        payload = payload.model_dump(mode="json")
    return json.dumps(payload, indent=2).encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    server_version = "PolicyTraceFullStackGuide/1.3"

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, status: int, payload: Any) -> None:
        self._send(status, _json_bytes(payload), "application/json; charset=utf-8")

    def _send_error(
        self,
        status: int,
        message: object,
        *,
        error_type: str,
        public_message: str | None = None,
    ) -> None:
        error_id, safe_message = _record_error(
            method=self.command,
            path=self.path,
            status=status,
            message=message,
            error_type=error_type,
        )
        self._send_json(
            status,
            {
                "error": public_message or safe_message,
                "error_id": error_id,
            },
        )

    def _body_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        value = json.loads(raw.decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("request body must be a JSON object")
        return value

    def _static(self, filename: str, content_type: str) -> None:
        path = APP_DIR / filename
        if not path.exists():
            self._send_error(
                404,
                f"static file not found: {filename}",
                error_type="NotFound",
                public_message="not found",
            )
            return
        self._send(200, path.read_bytes(), content_type)

    def do_GET(self) -> None:
        if self.path in {"/", "/index.html"}:
            self._static("index.html", "text/html; charset=utf-8")
            return
        if self.path == "/app.js":
            self._static("app.js", "text/javascript; charset=utf-8")
            return
        if self.path == "/styles.css":
            self._static("styles.css", "text/css; charset=utf-8")
            return
        if self.path == "/favicon.ico":
            self._send(204, b"", "image/x-icon")
            return
        if self.path == "/api/analysis":
            self._send_json(200, STATE.analysis)
            return
        if self.path == "/api/provider":
            self._send_json(200, STATE.provider.status())
            return
        if self.path == "/api/source/policy/status":
            self._send_json(200, STATE.policy_status_payload())
            return
        if self.path == "/api/source/comments/status":
            self._send_json(200, STATE.comment_corpus_status())
            return
        if self.path == "/api/revision-comparison":
            self._send_json(200, STATE.revision_comparison_payload())
            return
        if self.path == "/api/news/status":
            self._send_json(200, STATE.news_status_payload())
            return
        if self.path == "/api/audit-log":
            self._send_json(200, {"text": STATE.evidence_audit_log()})
            return
        if self.path == "/api/errors":
            self._send_json(
                200,
                {
                    "errors": _recent_errors(),
                    "log_file": str(ERROR_LOG_PATH.relative_to(ROOT)),
                },
            )
            return
        self._send_error(
            404,
            f"unknown route: {self.path}",
            error_type="NotFound",
            public_message="not found",
        )

    def do_POST(self) -> None:
        if not _STATE_WRITE_LOCK.acquire(blocking=False):
            self._send_error(
                409,
                "Another PolicyTrace operation is still running. Wait for it to finish before starting another.",
                error_type="Busy",
            )
            return

        try:
            self._do_post_locked()
        finally:
            _STATE_WRITE_LOCK.release()

    def _do_post_locked(self) -> None:
        try:
            body = self._body_json()
            if self.path == "/api/provider":
                self._send_json(200, STATE.provider.configure(body))
                return
            if self.path == "/api/provider/clear":
                STATE.provider.clear()
                self._send_json(200, STATE.provider.status())
                return

            if self.path == "/api/source/load":
                result = STATE.load_policy(
                    str(body.get("document_number", ""))
                )
            elif self.path == "/api/revision-compare":
                result = STATE.compare_revision(
                    str(body.get("document_number", ""))
                )
            elif self.path == "/api/news":
                try:
                    max_articles = int(body.get("max_articles", 8))
                except (TypeError, ValueError) as exc:
                    raise ValueError("max_articles must be an integer") from exc
                result = STATE.discover_news(
                    query=str(body.get("query", "")),
                    max_articles=max_articles,
                )
            elif self.path == "/api/news/use":
                result = STATE.set_news_article_use(
                    str(body.get("claim_id", "")),
                    use=bool(body.get("use", True)),
                )
            elif self.path == "/api/source/comments":
                try:
                    max_comments = int(body.get("max_comments", 12))
                except (TypeError, ValueError) as exc:
                    raise ValueError("max_comments must be an integer") from exc
                result = STATE.load_comments(
                    str(body.get("docket_id", "")),
                    max_comments=max_comments,
                )
            elif self.path == "/api/reset":
                result = STATE.reset(str(body.get("mode", "guided")))
            elif self.path == "/api/guided/begin":
                result = STATE.guided_begin(body.get("step_id"))
            elif self.path == "/api/guided/clarify":
                result = STATE.guided_clarify(str(body.get("note", "")))
            elif self.path == "/api/guided/edit":
                result = STATE.guided_edit(
                    str(body.get("claim_id", "")),
                    str(body.get("text", "")),
                )
            elif self.path == "/api/guided/flag":
                note = body.get("note")
                result = STATE.guided_flag(
                    str(body.get("claim_id", "")),
                    None if note is None else str(note),
                )
            elif self.path == "/api/guided/verify":
                result = STATE.guided_verify(str(body.get("claim_id", "")))
            elif self.path == "/api/guided/next":
                result = STATE.guided_next()
            elif self.path == "/api/rush/run":
                result = STATE.run_rush()
            elif self.path == "/api/rush/open":
                result = STATE.rush_open(str(body.get("step_id", "")))
            elif self.path == "/api/rush/final":
                result = STATE.rush_final()
            elif self.path == "/api/rush/approve":
                result = STATE.rush_approve(
                    bool(body.get("acknowledge_unreviewed", False)),
                    bool(body.get("acknowledge_flags", False)),
                )
            elif self.path == "/api/reanalysis/step":
                claim_id = str(body.get("claim_id", "")).strip() or None
                result = STATE.reanalyze(
                    str(body.get("step_id", "")),
                    str(body.get("text", "")),
                    claim_id=claim_id,
                    human_edited=bool(body.get("human_edited", True)),
                )
            elif self.path == "/api/reanalysis/refresh":
                result = STATE.refresh(str(body.get("step_id", "")))
            elif self.path == "/api/reanalysis/review":
                result = STATE.review_reanalysis(str(body.get("step_id", "")))
            elif self.path == "/api/brief":
                result = STATE.brief()
            elif self.path == "/api/final/approve":
                result = STATE.approve_final_brief(
                    acknowledge_flags=bool(body.get("acknowledge_flags", False))
                )
            else:
                self._send_error(
                    404,
                    f"unknown route: {self.path}",
                    error_type="NotFound",
                    public_message="not found",
                )
                return
            self._send_json(200, result)
        except (ValueError, json.JSONDecodeError) as exc:
            self._send_error(
                400,
                exc,
                error_type=type(exc).__name__,
            )
        except RuntimeError as exc:
            self._send_error(
                502,
                exc,
                error_type=type(exc).__name__,
            )
        except Exception as exc:
            self._send_error(
                500,
                exc,
                error_type=type(exc).__name__,
                public_message="Unexpected server error.",
            )

    def log_message(self, format: str, *args: Any) -> None:
        print(f"[FULL STACK GUIDE] {self.address_string()} - {format % args}")


def main() -> None:
    missing = [
        name
        for name in ("index.html", "app.js", "styles.css")
        if not (APP_DIR / name).exists()
    ]
    if missing:
        raise SystemExit(f"missing guide files: {', '.join(missing)}")

    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print("PolicyTrace Full-Stack Reference")
    print("==============================")
    print(f"Open http://{HOST}:{PORT}/")
    print("Guide app only. Does not modify the human frontend.")
    print("Provider credentials entered in the browser stay in this Python process only.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping full-stack guide.")


if __name__ == "__main__":
    main()
