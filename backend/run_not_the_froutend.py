from __future__ import annotations

import json
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

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
from selective_reanalysis import ReanalysisResult, build_final_brief, reanalyze_step, refresh_step


ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "not-the-froutend" / "index.html"
HOST = "127.0.0.1"
PORT = 8765

RAW_TEXT = (
    "Section one creates a reporting duty. "
    "Section two identifies covered providers. "
    "Section three sets a filing deadline."
)


def _evidence(
    evidence_id: str,
    source_id: str,
    snippet: str,
) -> Evidence:
    start = RAW_TEXT.index(snippet)
    return Evidence(
        id=evidence_id,
        source_id=source_id,
        snippet=snippet,
        start_offset=start,
        end_offset=start + len(snippet),
        retrieved_at=datetime(2026, 9, 23, tzinfo=timezone.utc),
    )


def _claim(claim_id: str, text: str, evidence_id: str) -> Claim:
    return Claim(
        id=claim_id,
        text=text,
        information_type=InformationType.AI_INTERPRETATION,
        evidence_ids=[evidence_id],
        verification_status=VerificationStatus.SUPPORTED,
        confidence="high",
    )


def make_demo_analysis() -> AnalysisRun:
    """Create a tiny, fully reviewed graph used only by NOT THE FROUTEND."""
    source = Source(
        id="source-policy",
        title="Demo policy",
        information_type=InformationType.OFFICIAL_POLICY,
        raw_text=RAW_TEXT,
        pii_redaction_status=PiiRedactionStatus.NOT_APPLICABLE,
    )
    evidence_one = _evidence(
        "evidence-one",
        source.id,
        "Section one creates a reporting duty.",
    )
    evidence_two = _evidence(
        "evidence-two",
        source.id,
        "Section two identifies covered providers.",
    )
    evidence_three = _evidence(
        "evidence-three",
        source.id,
        "Section three sets a filing deadline.",
    )

    reviewed = HumanReview(status=HumanReviewStatus.REVIEWED)
    steps = [
        AnalysisStep(
            id="step-one",
            kind=StepKind.POLICY_UNDERSTANDING,
            title="Understand policy",
            status=StepStatus.VERIFIED,
            claims=[
                _claim(
                    "claim-one",
                    "The policy creates a reporting duty.",
                    evidence_one.id,
                )
            ],
            human_review=reviewed.model_copy(deep=True),
        ),
        AnalysisStep(
            id="step-two",
            kind=StepKind.MAJOR_PROVISIONS,
            title="Major provisions",
            status=StepStatus.VERIFIED,
            depends_on=["step-one"],
            claims=[
                _claim(
                    "claim-two",
                    "Covered providers are identified.",
                    evidence_two.id,
                )
            ],
            human_review=reviewed.model_copy(deep=True),
            version=2,
        ),
        AnalysisStep(
            id="step-sibling",
            kind=StepKind.AFFECTED_PROGRAMS,
            title="Unrelated sibling",
            status=StepStatus.VERIFIED,
            depends_on=["step-one"],
            claims=[
                _claim(
                    "claim-sibling",
                    "A separate reviewed finding remains stable.",
                    evidence_one.id,
                )
            ],
            human_review=reviewed.model_copy(deep=True),
            version=4,
        ),
        AnalysisStep(
            id="step-three",
            kind=StepKind.STAKEHOLDERS,
            title="Stakeholders",
            status=StepStatus.VERIFIED,
            depends_on=["step-two"],
            claims=[
                _claim(
                    "claim-three",
                    "Covered providers are directly affected.",
                    evidence_two.id,
                )
            ],
            human_review=reviewed.model_copy(deep=True),
        ),
        AnalysisStep(
            id="step-four",
            kind=StepKind.PUBLIC_RESPONSE,
            title="Public response",
            status=StepStatus.VERIFIED,
            depends_on=["step-three"],
            claims=[
                _claim(
                    "claim-four",
                    "The filing deadline is part of the analyzed material.",
                    evidence_three.id,
                )
            ],
            human_review=reviewed.model_copy(deep=True),
        ),
    ]

    return AnalysisRun(
        id="not-the-froutend-demo",
        mode=AnalysisMode.GUIDED,
        policy=Policy(
            id="policy-demo",
            title="Demo policy",
            jurisdiction="Demo only",
            source_ids=[source.id],
        ),
        sources=[source],
        evidence=[evidence_one, evidence_two, evidence_three],
        steps=steps,
        current_step_id=None,
        final_review_status=HumanReviewStatus.APPROVED,
    )


class DemoState:
    def __init__(self) -> None:
        self.analysis = make_demo_analysis()

    def reset(self) -> AnalysisRun:
        self.analysis = make_demo_analysis()
        return self.analysis

    def reanalyze(self, step_id: str, text: str) -> AnalysisRun:
        replacement_text = text.strip()
        if not replacement_text:
            raise ValueError("replacement claim text must not be empty")

        def regenerate(
            snapshot: AnalysisRun,
            selected: AnalysisStep,
        ) -> ReanalysisResult:
            del snapshot
            replacement = selected.model_copy(deep=True)
            if not replacement.claims:
                raise ValueError("selected demo step has no claim to replace")
            replacement.claims[0].text = replacement_text
            replacement.claims[0].verification_status = VerificationStatus.NEEDS_HUMAN_REVIEW
            replacement.claims[0].verification_note = (
                "NOT THE FROUTEND demo re-analysis changed this claim; "
                "human demo review is required."
            )
            return ReanalysisResult(step=replacement)

        self.analysis = reanalyze_step(self.analysis, step_id, regenerate)
        return self.analysis

    def refresh(self, step_id: str) -> AnalysisRun:
        def regenerate(
            snapshot: AnalysisRun,
            selected: AnalysisStep,
        ) -> ReanalysisResult:
            del snapshot
            replacement = selected.model_copy(deep=True)
            replacement.ai_output = (
                (replacement.ai_output or replacement.title)
                + " [refreshed from current dependencies]"
            )
            for claim in replacement.claims:
                claim.verification_status = VerificationStatus.NEEDS_HUMAN_REVIEW
                claim.verification_note = (
                    "NOT THE FROUTEND demo refreshed this dependent section; "
                    "human demo review is required."
                )
            return ReanalysisResult(step=replacement)

        self.analysis = refresh_step(self.analysis, step_id, regenerate)
        return self.analysis

    def review(self, step_id: str) -> AnalysisRun:
        step = next(
            (item for item in self.analysis.steps if item.id == step_id),
            None,
        )
        if step is None:
            raise ValueError(f"unknown analysis step {step_id!r}")
        if step.status == StepStatus.NEEDS_REFRESH:
            raise ValueError("refresh this step before marking it reviewed")

        # This is intentionally a demo-only acceptance button, not semantic verification.
        for claim in step.claims:
            if claim.verification_status == VerificationStatus.NEEDS_HUMAN_REVIEW:
                claim.verification_status = VerificationStatus.SUPPORTED
                claim.verification_note = (
                    "Accepted by the human in NOT THE FROUTEND demo. "
                    "This button is not a semantic verifier."
                )
        step.status = StepStatus.VERIFIED
        step.human_review.status = HumanReviewStatus.REVIEWED
        self.analysis = AnalysisRun.model_validate(
            self.analysis.model_dump(mode="python")
        )
        return self.analysis

    def brief(self) -> AnalysisRun:
        self.analysis = build_final_brief(self.analysis)
        return self.analysis


STATE = DemoState()


def _json_bytes(payload: Any) -> bytes:
    if isinstance(payload, AnalysisRun):
        data = payload.model_dump(mode="json")
    else:
        data = payload
    return json.dumps(data, indent=2).encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    server_version = "PolicyTraceNotTheFroutend/1.0"

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

    def do_GET(self) -> None:
        if self.path in {"/", "/index.html"}:
            self._send(
                200,
                PAGE.read_bytes(),
                "text/html; charset=utf-8",
            )
            return
        if self.path == "/api/state":
            self._send_json(200, STATE.analysis)
            return
        self._send_json(404, {"error": "not found"})

    def do_POST(self) -> None:
        try:
            body = self._body_json()
            if self.path == "/api/reset":
                result = STATE.reset()
            elif self.path == "/api/reanalyze":
                result = STATE.reanalyze(
                    str(body.get("step_id", "")),
                    str(body.get("text", "")),
                )
            elif self.path == "/api/refresh":
                result = STATE.refresh(str(body.get("step_id", "")))
            elif self.path == "/api/review":
                result = STATE.review(str(body.get("step_id", "")))
            elif self.path == "/api/brief":
                result = STATE.brief()
            else:
                self._send_json(404, {"error": "not found"})
                return
            self._send_json(200, result)
        except (ValueError, json.JSONDecodeError) as exc:
            self._send_json(400, {"error": str(exc)})

    def log_message(self, format: str, *args: Any) -> None:
        print(f"[NOT THE FROUTEND] {self.address_string()} - {format % args}")


def main() -> None:
    if not PAGE.exists():
        raise SystemExit(f"missing demo page: {PAGE}")
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print("NOT THE FROUTEND")
    print("================")
    print(f"Open http://{HOST}:{PORT}/")
    print("This is a throwaway Chunk 9 wiring harness, not the real frontend.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping NOT THE FROUTEND.")


if __name__ == "__main__":
    main()
