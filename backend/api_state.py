"""Single-process state and workflow adapters for the FastAPI demo."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from threading import RLock
from urllib.parse import urlsplit

from build_evidence_demo import DEFAULT_QUERY
from evidence import build_chunk3_demo_analysis
from federal_register import NormalizedPolicyDocument, fetch_and_normalize, load_fixture_and_normalize
from foundry_client import FoundryChatClient, FoundryConfig
from guided_review import (
    begin_guided_review, clarify_current_step, edit_current_claim,
    flag_current_claim, next_guided_step, verify_current_claim,
)
from models import AnalysisMode, AnalysisRun, HumanReviewStatus, InformationType, StepStatus, VerificationStatus
from openai_client import OpenAIChatClient, OpenAIConfig
from openrouter_client import DEFAULT_OPENROUTER_BASE_URL, DEFAULT_OPENROUTER_MODEL, OpenRouterChatClient, OpenRouterConfig
from policy_input import document_from_file, document_from_pasted_text, federal_register_document_number
from policy_interpreter import run_policy_interpreter
from response_sources import fetch_comments_for_docket, source_from_response_record
from response_viewpoint_analyst import run_response_viewpoint_analyst
from rush_mode import (
    approve_rush_final_review, combine_analysis_runs, open_rush_step_for_review,
    return_to_rush_final_review, run_rush_analysis,
)
from selective_reanalysis import ReanalysisResult, build_final_brief, reanalyze_step, refresh_step
from source_ingest import SourceInputError, fetch_source_url


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "data/federal-register/2024-20529.fixture.json"


class ExternalServiceError(RuntimeError):
    """An upstream source or model failed."""


def _copy(analysis: AnalysisRun) -> AnalysisRun:
    return AnalysisRun.model_validate(analysis.model_dump(mode="python"))


class RuntimeProvider:
    def __init__(self) -> None:
        self.kind = "none"
        self.model = ""
        self.base_url = ""
        self.endpoint = ""
        self.api_key = ""
        self.bearer_token = ""
        self.regulations_api_key = os.getenv("REGULATIONS_GOV_API_KEY", "")
        foundry_key = os.getenv("POLICYTRACE_FOUNDRY_API_KEY", "")
        foundry_token = os.getenv("POLICYTRACE_FOUNDRY_BEARER_TOKEN", "")
        if (os.getenv("POLICYTRACE_FOUNDRY_ENDPOINT") and os.getenv("POLICYTRACE_FOUNDRY_MODEL")
                and bool(foundry_key) != bool(foundry_token)):
            self.configure({
                "kind": "foundry",
                "endpoint": os.getenv("POLICYTRACE_FOUNDRY_ENDPOINT", ""),
                "model": os.getenv("POLICYTRACE_FOUNDRY_MODEL", ""),
                "api_key": foundry_key,
                "bearer_token": foundry_token,
                "regulations_api_key": self.regulations_api_key,
            })

    def status(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "model": self.model,
            "base_url": self.base_url,
            "endpoint": self.endpoint,
            "has_api_key": bool(self.api_key),
            "has_bearer_token": bool(self.bearer_token),
            "has_regulations_api_key": bool(self.regulations_api_key),
            "credentials_storage": "process_memory_only",
        }

    def configure(self, data: dict[str, str]) -> dict[str, object]:
        kind = data.get("kind", "foundry").strip().lower()
        model = data.get("model", "").strip()
        endpoint = data.get("endpoint", "").strip()
        base_url = data.get("base_url", "").strip()
        api_key = data.get("api_key", "").strip()
        bearer_token = data.get("bearer_token", "").strip()
        regulations_api_key = data.get("regulations_api_key", "").strip()
        if kind == "foundry":
            if not endpoint or not model or bool(api_key) == bool(bearer_token):
                raise ValueError("Foundry needs an endpoint, model, and exactly one API key or bearer token.")
        elif kind == "openai":
            if not api_key or not model:
                raise ValueError("OpenAI needs an API key and model.")
        elif kind == "openrouter":
            if not api_key:
                raise ValueError("OpenRouter needs an API key.")
            model = model or DEFAULT_OPENROUTER_MODEL
            base_url = base_url or DEFAULT_OPENROUTER_BASE_URL
        else:
            raise ValueError("Choose Foundry, OpenAI, or OpenRouter.")
        self.kind, self.model, self.endpoint, self.base_url = kind, model, endpoint, base_url
        self.api_key, self.bearer_token = api_key, bearer_token
        self.regulations_api_key = regulations_api_key
        return self.status()

    def clear(self) -> dict[str, object]:
        self.kind = "none"
        self.model = self.endpoint = self.base_url = ""
        self.api_key = self.bearer_token = self.regulations_api_key = ""
        return self.status()

    def model_call(self) -> Callable[[str, str], str]:
        if self.kind == "foundry":
            return FoundryChatClient(FoundryConfig(
                endpoint=self.endpoint, model=self.model,
                api_key=self.api_key or None, bearer_token=self.bearer_token or None,
            )).complete_json
        if self.kind == "openai":
            return OpenAIChatClient(OpenAIConfig(
                api_key=self.api_key, model=self.model, base_url=self.base_url or "https://api.openai.com/v1",
            )).complete_json
        if self.kind == "openrouter":
            return OpenRouterChatClient(OpenRouterConfig(
                api_key=self.api_key, model=self.model, base_url=self.base_url,
            )).complete_json
        raise ValueError("Configure a model provider before analyzing a source.")


class AppState:
    def __init__(self) -> None:
        self.lock = RLock()
        self.provider = RuntimeProvider()
        self.document: NormalizedPolicyDocument | None = None
        self.policy_analysis: AnalysisRun | None = None
        self.response_analysis: AnalysisRun | None = None
        self.analysis = build_chunk3_demo_analysis(load_fixture_and_normalize(FIXTURE), query=DEFAULT_QUERY)
        self.analysis.current_step_id = None

    def _store_policy(
        self, document: NormalizedPolicyDocument,
        *, source_type: InformationType = InformationType.OFFICIAL_POLICY,
        source_url: str | None = None,
    ) -> AnalysisRun:
        model_call = self.provider.model_call()
        try:
            result = run_policy_interpreter(
                document, model_call, mode=AnalysisMode.GUIDED,
                source_information_type=source_type, source_url=source_url,
            )
        except Exception as exc:
            raise ExternalServiceError(f"Policy analysis failed: {exc}") from exc
        result.current_step_id = None
        self.document = document
        self.policy_analysis = _copy(result)
        self.response_analysis = None
        self.analysis = _copy(result)
        return self.analysis

    def load_federal_register(self, value: str) -> AnalysisRun:
        number = federal_register_document_number(value)
        self.provider.model_call()
        try:
            document = fetch_and_normalize(number)
        except Exception as exc:
            raise ExternalServiceError(f"Could not load Federal Register document {number}: {exc}") from exc
        return self._store_policy(document)

    def load_url(self, url: str) -> AnalysisRun:
        if urlsplit(url).hostname in {"federalregister.gov", "www.federalregister.gov"}:
            return self.load_federal_register(url)
        self.provider.model_call()
        try:
            title, text, final_url = fetch_source_url(url)
        except SourceInputError as exc:
            if "could not be fetched" in str(exc):
                raise ExternalServiceError(str(exc)) from exc
            raise
        document, source_type = document_from_pasted_text(text, title=title)
        return self._store_policy(document, source_type=source_type, source_url=final_url)

    def load_text(self, text: str, title: str | None = None) -> AnalysisRun:
        document, source_type = document_from_pasted_text(text, title=title)
        return self._store_policy(document, source_type=source_type)

    def load_file(self, filename: str, data: bytes, content_type: str, title: str | None = None) -> AnalysisRun:
        if not filename.strip():
            raise SourceInputError("Choose a file to upload.")
        document, source_type = document_from_file(filename, data, content_type, title=title)
        return self._store_policy(document, source_type=source_type)

    def load_comments(self, docket_id: str, max_comments: int) -> AnalysisRun:
        if not docket_id.strip():
            raise ValueError("Enter a Regulations.gov docket ID.")
        if self.document is None or self.policy_analysis is None:
            raise ValueError("Load a policy before loading public comments.")
        if self.policy_analysis.sources[0].information_type != InformationType.OFFICIAL_POLICY:
            raise ValueError("Public comments currently require a Federal Register policy.")
        if not self.provider.regulations_api_key:
            raise ValueError("A Regulations.gov API key is required for public comments.")
        if not 1 <= max_comments <= 100:
            raise ValueError("Comment count must be between 1 and 100.")
        model_call = self.provider.model_call()
        try:
            records = fetch_comments_for_docket(docket_id.strip(), api_key=self.provider.regulations_api_key, max_comments=max_comments)
        except Exception as exc:
            raise ExternalServiceError(f"Could not load Regulations.gov docket {docket_id}: {exc}") from exc
        if not records:
            raise ValueError("No usable public comments were returned for this docket.")
        try:
            response = run_response_viewpoint_analyst(
                self.document, [source_from_response_record(item) for item in records],
                model_call, mode=AnalysisMode.GUIDED,
            )
        except Exception as exc:
            raise ExternalServiceError(f"Public response analysis failed: {exc}") from exc
        combined = combine_analysis_runs(self.policy_analysis, response)
        combined.mode = AnalysisMode.GUIDED
        combined.current_step_id = None
        for step in combined.steps:
            step.human_review.status = HumanReviewStatus.NOT_REVIEWED
        self.response_analysis = response
        self.analysis = _copy(combined)
        return self.analysis

    def reset(self) -> AnalysisRun:
        self.analysis = _copy(self.policy_analysis) if self.policy_analysis else build_chunk3_demo_analysis(
            load_fixture_and_normalize(FIXTURE), query=DEFAULT_QUERY,
        )
        if self.response_analysis and self.policy_analysis:
            combined = combine_analysis_runs(self.policy_analysis, self.response_analysis)
            combined.mode = AnalysisMode.GUIDED
            combined.current_step_id = None
            self.analysis = _copy(combined)
        self.analysis.current_step_id = None
        return self.analysis

    def guided_begin(self, step_id: str | None = None) -> AnalysisRun:
        if self.analysis.mode != AnalysisMode.GUIDED:
            raise ValueError("Reset to Guided mode before beginning Guided review.")
        if step_id:
            ids = [step.id for step in self.analysis.steps]
            if step_id not in ids:
                raise ValueError("Unknown analysis step.")
            current = self.analysis.current_step_id
            allowed_index = ids.index(current) if current else next(
                (index for index, step in enumerate(self.analysis.steps)
                 if step.human_review.status not in {HumanReviewStatus.REVIEWED, HumanReviewStatus.APPROVED}),
                len(ids) - 1,
            )
            if ids.index(step_id) > allowed_index:
                raise ValueError("Advance with Next before opening a future step.")
        self.analysis = begin_guided_review(self.analysis, step_id=step_id)
        return self.analysis

    def guided_verify(self, claim_id: str) -> AnalysisRun:
        current = next((step for step in self.analysis.steps if step.id == self.analysis.current_step_id), None)
        if current is None or not any(claim.id == claim_id for claim in current.claims):
            raise ValueError("Claim is not in the current review step.")
        try:
            self.analysis = verify_current_claim(self.analysis, claim_id, self.provider.model_call())
        except Exception:
            fallback = _copy(self.analysis)
            step = next(item for item in fallback.steps if item.id == fallback.current_step_id)
            claim = next(item for item in step.claims if item.id == claim_id)
            claim.verification_status = VerificationStatus.NEEDS_HUMAN_REVIEW
            claim.verification_note = "Verification provider failed; this claim still needs human review."
            step.human_review.status = HumanReviewStatus.IN_REVIEW
            self.analysis = _copy(fallback)
        return self.analysis

    def rush_run(self) -> AnalysisRun:
        if self.policy_analysis is None:
            raise ValueError("Load a policy before running Rush mode.")
        response = self.response_analysis
        if response is None:
            response = AnalysisRun(
                id=f"empty-{self.policy_analysis.id}", mode=AnalysisMode.GUIDED,
                policy=self.policy_analysis.policy.model_copy(update={"source_ids": []}),
                sources=[], evidence=[], steps=[],
            )
        try:
            result = run_rush_analysis(self.policy_analysis, response, self.provider.model_call())
        except Exception as exc:
            raise ExternalServiceError(f"Rush analysis failed: {exc}") from exc
        self.analysis = result
        return result

    def reanalyze(self, step_id: str, text: str) -> AnalysisRun:
        if not text.strip():
            raise ValueError("Enter replacement claim text.")
        def regenerate(snapshot, step):
            del snapshot
            replacement = step.model_copy(deep=True)
            if not replacement.claims:
                raise ValueError("This step has no claim to replace.")
            if replacement.claims[0].original_text is None:
                replacement.claims[0].original_text = replacement.claims[0].text
            replacement.claims[0].text = text.strip()
            replacement.claims[0].information_type = InformationType.HUMAN_INTERPRETATION
            replacement.claims[0].verification_status = VerificationStatus.NEEDS_HUMAN_REVIEW
            replacement.claims[0].verification_note = "Edited section requires re-verification."
            return ReanalysisResult(step=replacement)
        self.analysis = reanalyze_step(self.analysis, step_id, regenerate)
        return self.analysis

    def refresh(self, step_id: str) -> AnalysisRun:
        def regenerate(snapshot, step):
            del snapshot
            replacement = step.model_copy(deep=True)
            for claim in replacement.claims:
                claim.verification_status = VerificationStatus.NEEDS_HUMAN_REVIEW
                claim.verification_note = "Refreshed section requires re-verification."
            return ReanalysisResult(step=replacement)
        self.analysis = refresh_step(self.analysis, step_id, regenerate)
        return self.analysis

    def review_reanalysis(self, step_id: str) -> AnalysisRun:
        result = _copy(self.analysis)
        step = next((item for item in result.steps if item.id == step_id), None)
        if step is None:
            raise ValueError("Unknown analysis step.")
        if step.status == StepStatus.NEEDS_REFRESH:
            raise ValueError("Refresh this step before marking it reviewed.")
        if any(claim.verification_status == VerificationStatus.NEEDS_HUMAN_REVIEW for claim in step.claims):
            raise ValueError("Verify claims in this step before marking it reviewed.")
        step.status = StepStatus.VERIFIED
        step.human_review.status = HumanReviewStatus.REVIEWED
        self.analysis = _copy(result)
        return self.analysis


STATE = AppState()
