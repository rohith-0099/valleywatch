"""Web API between the dashboard and the analysis pipeline.

Run from the backend folder:

    ../.venv/bin/uvicorn api:app --port 8000

The dashboard starts an analysis, polls its progress messages, and then
loads the result layers as GeoJSON.
"""
import json
import threading
import traceback
from datetime import date
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

from copilot.facts import RunFacts
from copilot.llm import answer
from copilot.report import build_report
from valleywatch import fetch
from valleywatch.config import Settings
from valleywatch.pipeline import REPO_ROOT, output_name, run_analysis

OUTPUTS = REPO_ROOT / "outputs"
LAYERS = ("flood_debris", "buildings_hit", "road_hits", "bridges",
          "settlements", "broken_links", "lost_routes")

app = FastAPI(title="ValleyWatch")
# The dashboard runs on another port during development.
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                   allow_headers=["*"])

# One entry per analysis started since the server came up:
# {run_id: {"status": "running" | "done" | "failed", "messages": [...]}}
jobs = {}


class AnalysisRequest(BaseModel):
    bbox: list[float]          # west, south, east, north in degrees
    flood_date: date
    allow_large: bool = False  # large boxes take tens of minutes
    thorough: bool = False     # also use a second radar track (slower)


def _work(run_id, bbox, flood_date, settings):
    job = jobs[run_id]
    try:
        run_analysis(bbox, flood_date, settings, progress=job["messages"].append)
        job["status"] = "done"
    except Exception as error:  # noqa: BLE001 - shown to the user
        traceback.print_exc()
        job["messages"].append(f"Failed: {error}")
        job["status"] = "failed"


@app.post("/api/analyse")
def start_analysis(request: AnalysisRequest):
    if len(request.bbox) != 4 or request.bbox[0] >= request.bbox[2] or request.bbox[1] >= request.bbox[3]:
        raise HTTPException(400, "bbox must be west, south, east, north")
    bbox = tuple(round(v, 3) for v in request.bbox)
    area = fetch.bbox_area_km2(bbox)
    settings = Settings()
    settings.use_second_track = request.thorough
    limit = settings.max_live_area_km2
    if area > limit and not request.allow_large:
        raise HTTPException(400, f"The box covers {area:.0f} km2. Live runs are limited "
                                 f"to {limit:.0f} km2. Draw a smaller box.")
    run_id = output_name(bbox, request.flood_date, settings)
    if run_id in jobs and jobs[run_id]["status"] == "running":
        return {"run_id": run_id}
    jobs[run_id] = {"status": "running", "messages": []}
    threading.Thread(target=_work, args=(run_id, bbox, request.flood_date, settings),
                     daemon=True).start()
    return {"run_id": run_id}


@app.get("/api/jobs/{run_id}")
def job_progress(run_id: str):
    if run_id not in jobs:
        raise HTTPException(404, "No such analysis in this session")
    return jobs[run_id]


def _run_folder(run_id):
    folder = (OUTPUTS / run_id).resolve()
    # Refuse names that would step outside the outputs folder.
    if folder.parent != OUTPUTS.resolve() or not (folder / "summary.json").exists():
        raise HTTPException(404, "No such run")
    return folder


@app.get("/api/runs")
def list_runs():
    """Finished runs on disk, newest first."""
    runs = []
    if OUTPUTS.exists():
        for summary_path in sorted(OUTPUTS.glob("*/summary.json"),
                                   key=lambda p: p.stat().st_mtime, reverse=True):
            summary = json.loads(summary_path.read_text())
            if "cutoff" in summary:  # only complete runs
                runs.append({"run_id": summary_path.parent.name, **summary["inputs"]})
    return runs


@app.get("/api/runs/{run_id}/summary")
def run_summary(run_id: str):
    return json.loads((_run_folder(run_id) / "summary.json").read_text())


@app.get("/api/runs/{run_id}/layers/{layer}")
def run_layer(run_id: str, layer: str):
    if layer not in LAYERS:
        raise HTTPException(404, "No such layer")
    return FileResponse(_run_folder(run_id) / f"{layer}.geojson", media_type="application/geo+json")


@app.get("/api/runs/{run_id}/quicklook")
def run_quicklook(run_id: str):
    return FileResponse(_run_folder(run_id) / "quicklook.png", media_type="image/png")


class Question(BaseModel):
    question: str
    language: str = "en"  # "en" or "ne"


@app.post("/api/runs/{run_id}/ask")
def ask_copilot(run_id: str, body: Question):
    """Answer a question from the computed data of one run."""
    language = body.language if body.language in ("en", "ne") else "en"
    try:
        return answer(RunFacts(_run_folder(run_id)), body.question[:1000], language)
    except RuntimeError as error:
        raise HTTPException(502, str(error))


@app.get("/api/runs/{run_id}/report", response_class=HTMLResponse)
def situation_report(run_id: str, lang: str = "en", refresh: bool = False):
    """The one-page situation report as a printable page."""
    return build_report(RunFacts(_run_folder(run_id)), lang, refresh)
