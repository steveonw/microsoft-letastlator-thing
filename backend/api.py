"""FastAPI transport for the server-authoritative PolicyTrace workspace."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from api_state import ExternalServiceError, STATE
from guided_review import clarify_current_step, edit_current_claim, flag_current_claim, next_guided_step
from models import AnalysisMode, AnalysisRun, StepStatus
from rush_mode import approve_rush_final_review, open_rush_step_for_review, return_to_rush_final_review
from selective_reanalysis import build_final_brief
from source_ingest import MAX_SOURCE_BYTES


DEMO = Path(__file__).resolve().parents[1] / "frontend/demo"
app = FastAPI(title="PolicyTrace API")
T = TypeVar("T")


def action(operation: Callable[[], T]) -> T:
    """Serialize demo state changes and map workflow/upstream errors."""
    with STATE.lock:
        try:
            return operation()
        except ExternalServiceError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


def update_analysis(operation: Callable[[AnalysisRun], AnalysisRun]) -> AnalysisRun:
    def update() -> AnalysisRun:
        STATE.analysis = operation(STATE.analysis)
        return STATE.analysis
    return action(update)


class ProviderRequest(BaseModel):
    kind: str = "foundry"
    model: str = ""
    endpoint: str = ""
    base_url: str = ""
    api_key: str = ""
    bearer_token: str = ""
    regulations_api_key: str = ""


class DocumentNumberRequest(BaseModel):
    document_number: str


class UrlRequest(BaseModel):
    url: str


class TextRequest(BaseModel):
    text: str
    title: str | None = None


class CommentsRequest(BaseModel):
    docket_id: str
    max_comments: int = 12


class ResetRequest(BaseModel):
    mode: str = "guided"


class StepRequest(BaseModel):
    step_id: str | None = None


class NoteRequest(BaseModel):
    note: str


class ClaimRequest(BaseModel):
    claim_id: str


class EditRequest(ClaimRequest):
    text: str


class FlagRequest(ClaimRequest):
    note: str | None = None


class ReanalysisRequest(BaseModel):
    step_id: str
    text: str


@app.get("/api/analysis", response_model=AnalysisRun)
def get_analysis() -> AnalysisRun:
    return action(lambda: STATE.analysis)


@app.get("/api/provider")
def get_provider() -> dict[str, object]:
    return action(STATE.provider.status)


@app.post("/api/provider")
def set_provider(body: ProviderRequest) -> dict[str, object]:
    return action(lambda: STATE.provider.configure(body.model_dump()))


@app.post("/api/provider/clear")
def clear_provider() -> dict[str, object]:
    return action(STATE.provider.clear)


@app.post("/api/source/load", response_model=AnalysisRun)
def load_federal_register(body: DocumentNumberRequest) -> AnalysisRun:
    return action(lambda: STATE.load_federal_register(body.document_number))


@app.post("/api/source/url", response_model=AnalysisRun)
def load_url(body: UrlRequest) -> AnalysisRun:
    return action(lambda: STATE.load_url(body.url))


@app.post("/api/source/text", response_model=AnalysisRun)
def load_text(body: TextRequest) -> AnalysisRun:
    return action(lambda: STATE.load_text(body.text, body.title))


@app.post("/api/source/file", response_model=AnalysisRun)
async def load_file(request: Request, filename: str, title: str | None = None) -> AnalysisRun:
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_SOURCE_BYTES:
            raise HTTPException(status_code=400, detail="The source exceeds the 5 MB demo limit.")
    return action(lambda: STATE.load_file(filename, bytes(body), request.headers.get("content-type", ""), title))


@app.post("/api/source/comments", response_model=AnalysisRun)
def load_comments(body: CommentsRequest) -> AnalysisRun:
    return action(lambda: STATE.load_comments(body.docket_id, body.max_comments))


@app.post("/api/reset", response_model=AnalysisRun)
def reset(body: ResetRequest) -> AnalysisRun:
    if body.mode == "guided":
        return action(STATE.reset)
    if body.mode == "rush":
        return action(STATE.rush_run)
    raise HTTPException(status_code=400, detail="Mode must be guided or rush.")


@app.post("/api/guided/begin", response_model=AnalysisRun)
def guided_begin(body: StepRequest) -> AnalysisRun:
    return action(lambda: STATE.guided_begin(body.step_id))


@app.post("/api/guided/clarify", response_model=AnalysisRun)
def guided_clarify(body: NoteRequest) -> AnalysisRun:
    return update_analysis(lambda analysis: clarify_current_step(analysis, body.note))


@app.post("/api/guided/edit", response_model=AnalysisRun)
def guided_edit(body: EditRequest) -> AnalysisRun:
    return update_analysis(lambda analysis: edit_current_claim(analysis, body.claim_id, body.text))


@app.post("/api/guided/flag", response_model=AnalysisRun)
def guided_flag(body: FlagRequest) -> AnalysisRun:
    return update_analysis(lambda analysis: flag_current_claim(analysis, body.claim_id, body.note))


@app.post("/api/guided/verify", response_model=AnalysisRun)
def guided_verify(body: ClaimRequest) -> AnalysisRun:
    return action(lambda: STATE.guided_verify(body.claim_id))


@app.post("/api/guided/next", response_model=AnalysisRun)
def guided_next() -> AnalysisRun:
    def advance(analysis: AnalysisRun) -> AnalysisRun:
        if analysis.mode != AnalysisMode.GUIDED:
            raise ValueError("Guided Next is only available in Guided mode.")
        return next_guided_step(analysis)
    return update_analysis(advance)


@app.post("/api/rush/run", response_model=AnalysisRun)
def rush_run() -> AnalysisRun:
    return action(STATE.rush_run)


@app.post("/api/rush/open", response_model=AnalysisRun)
def rush_open(body: StepRequest) -> AnalysisRun:
    if not body.step_id:
        raise HTTPException(status_code=400, detail="Choose a step to open.")
    return update_analysis(lambda analysis: open_rush_step_for_review(analysis, body.step_id))


@app.post("/api/rush/final", response_model=AnalysisRun)
def rush_final() -> AnalysisRun:
    return update_analysis(return_to_rush_final_review)


@app.post("/api/rush/approve", response_model=AnalysisRun)
def rush_approve() -> AnalysisRun:
    def approve(analysis: AnalysisRun) -> AnalysisRun:
        if any(step.status == StepStatus.NEEDS_REFRESH for step in analysis.steps):
            raise ValueError("Refresh dependent steps before approving the analysis.")
        return approve_rush_final_review(analysis)
    return update_analysis(approve)


@app.post("/api/reanalysis/step", response_model=AnalysisRun)
def reanalyze(body: ReanalysisRequest) -> AnalysisRun:
    return action(lambda: STATE.reanalyze(body.step_id, body.text))


@app.post("/api/reanalysis/refresh", response_model=AnalysisRun)
def refresh(body: StepRequest) -> AnalysisRun:
    return action(lambda: STATE.refresh(body.step_id or ""))


@app.post("/api/reanalysis/review", response_model=AnalysisRun)
def review_reanalysis(body: StepRequest) -> AnalysisRun:
    return action(lambda: STATE.review_reanalysis(body.step_id or ""))


@app.post("/api/brief", response_model=AnalysisRun)
def build_brief() -> AnalysisRun:
    return update_analysis(build_final_brief)


@app.get("/", include_in_schema=False)
def home() -> RedirectResponse:
    return RedirectResponse(url="/demo/")


app.mount("/demo", StaticFiles(directory=DEMO, html=True), name="demo")
