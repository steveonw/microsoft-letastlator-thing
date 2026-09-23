from __future__ import annotations

import json
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from guided_review import (
    begin_guided_review,
    clarify_current_step,
    edit_current_claim,
    flag_current_claim,
    next_guided_step,
    verify_current_claim,
)
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
from rush_mode import (
    approve_rush_final_review,
    open_rush_step_for_review,
    return_to_rush_final_review,
    run_rush_analysis,
)
from selective_reanalysis import (
    ReanalysisResult,
    build_final_brief,
    reanalyze_step,
    refresh_step,
)


ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "guide" / "full-stack"
HOST = "127.0.0.1"
PORT = 8777

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
    response_ev = _evidence(
        response_source,
        "evidence-response",
        RESPONSE_TEXT,
    )
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


class GuideState:
    def __init__(self) -> None:
        self.analysis = make_guided_demo()

    def reset(self, mode: str = "guided") -> AnalysisRun:
        if mode == "rush":
            return self.run_rush()
        self.analysis = make_guided_demo()
        return self.analysis

    def guided_begin(self, step_id: str | None = None) -> AnalysisRun:
        self.analysis = begin_guided_review(self.analysis, step_id=step_id)
        return self.analysis

    def guided_clarify(self, note: str) -> AnalysisRun:
        self.analysis = clarify_current_step(self.analysis, note)
        return self.analysis

    def guided_edit(self, claim_id: str, text: str) -> AnalysisRun:
        self.analysis = edit_current_claim(self.analysis, claim_id, text)
        return self.analysis

    def guided_flag(self, claim_id: str, note: str | None) -> AnalysisRun:
        self.analysis = flag_current_claim(self.analysis, claim_id, note)
        return self.analysis

    def guided_verify(self, claim_id: str) -> AnalysisRun:
        self.analysis = verify_current_claim(
            self.analysis,
            claim_id,
            deterministic_verifier,
        )
        return self.analysis

    def guided_next(self) -> AnalysisRun:
        self.analysis = next_guided_step(self.analysis)
        return self.analysis

    def run_rush(self) -> AnalysisRun:
        policy_run, response_run = make_rush_inputs()
        self.analysis = run_rush_analysis(
            policy_run,
            response_run,
            deterministic_verifier,
        )
        return self.analysis

    def rush_open(self, step_id: str) -> AnalysisRun:
        self.analysis = open_rush_step_for_review(self.analysis, step_id)
        return self.analysis

    def rush_final(self) -> AnalysisRun:
        self.analysis = return_to_rush_final_review(self.analysis)
        return self.analysis

    def rush_approve(self) -> AnalysisRun:
        self.analysis = approve_rush_final_review(self.analysis)
        return self.analysis

    def reanalyze(self, step_id: str, text: str) -> AnalysisRun:
        replacement_text = text.strip()
        if not replacement_text:
            raise ValueError("replacement claim text must not be empty")

        def regenerate(snapshot: AnalysisRun, selected: AnalysisStep) -> ReanalysisResult:
            del snapshot
            replacement = selected.model_copy(deep=True)
            if not replacement.claims:
                raise ValueError("selected guide step has no claims")
            replacement.claims[0].text = replacement_text
            replacement.claims[0].verification_status = (
                VerificationStatus.NEEDS_HUMAN_REVIEW
            )
            replacement.claims[0].verification_note = (
                "Guide re-analysis changed this claim; re-verification is required."
            )
            return ReanalysisResult(step=replacement)

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

        for claim in step.claims:
            if claim.verification_status == VerificationStatus.NEEDS_HUMAN_REVIEW:
                checked = begin_guided_review(self.analysis, step_id=step.id)
                self.analysis = verify_current_claim(
                    checked,
                    claim.id,
                    deterministic_verifier,
                )
                step = next(item for item in self.analysis.steps if item.id == step_id)

        step.status = StepStatus.VERIFIED
        step.human_review.status = HumanReviewStatus.REVIEWED
        self.analysis = AnalysisRun.model_validate(
            self.analysis.model_dump(mode="python")
        )
        return self.analysis

    def brief(self) -> AnalysisRun:
        self.analysis = build_final_brief(self.analysis)
        return self.analysis


STATE = GuideState()


def _json_bytes(payload: Any) -> bytes:
    if isinstance(payload, AnalysisRun):
        payload = payload.model_dump(mode="json")
    return json.dumps(payload, indent=2).encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    server_version = "PolicyTraceFullStackGuide/1.0"

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, status: int, payload: Any) -> None:
        self._send(status, _json_bytes(payload), "application/json; charset=utf-8")

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
            self._send_json(404, {"error": "not found"})
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
        if self.path == "/api/analysis":
            self._send_json(200, STATE.analysis)
            return
        self._send_json(404, {"error": "not found"})

    def do_POST(self) -> None:
        try:
            body = self._body_json()
            if self.path == "/api/reset":
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
                result = STATE.rush_approve()
            elif self.path == "/api/reanalysis/step":
                result = STATE.reanalyze(
                    str(body.get("step_id", "")),
                    str(body.get("text", "")),
                )
            elif self.path == "/api/reanalysis/refresh":
                result = STATE.refresh(str(body.get("step_id", "")))
            elif self.path == "/api/reanalysis/review":
                result = STATE.review_reanalysis(str(body.get("step_id", "")))
            elif self.path == "/api/brief":
                result = STATE.brief()
            else:
                self._send_json(404, {"error": "not found"})
                return
            self._send_json(200, result)
        except (ValueError, json.JSONDecodeError) as exc:
            self._send_json(400, {"error": str(exc)})

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
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping full-stack guide.")


if __name__ == "__main__":
    main()
