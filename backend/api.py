"""Serve the demo UI and an analysis built by the existing evidence pipeline."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from build_evidence_demo import DEFAULT_QUERY
from evidence import build_chunk3_demo_analysis
from federal_register import load_fixture_and_normalize
from models import AnalysisRun


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "data/federal-register/2024-20529.fixture.json"
DEMO = ROOT / "frontend/demo"

app = FastAPI(title="PolicyTrace demo API")


@app.get("/api/analysis", response_model=AnalysisRun)
def get_analysis() -> AnalysisRun:
    """Build a traceable analysis from the checked-in Federal Register fixture."""
    document = load_fixture_and_normalize(FIXTURE)
    return build_chunk3_demo_analysis(document, query=DEFAULT_QUERY)


@app.get("/", include_in_schema=False)
def home() -> RedirectResponse:
    return RedirectResponse(url="/demo/")


app.mount("/demo", StaticFiles(directory=DEMO, html=True), name="demo")
