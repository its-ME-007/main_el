"""Phase 7: one application. FastAPI serves the exported results, runs pipeline steps as jobs, and serves the built UI.

  GET  /data/<area>/<file>.json|.geojson   exported results (same paths the Vite dev server serves)
  GET  /api/steps                          pipeline steps that can be run
  POST /api/jobs {"step", "area", "args"}  start `python -m urban.<step> <area> <args>`; one job at a time, because
                                           every SUMO step rewrites the shared route files in data/<area>/sim/
  GET  /api/jobs, /api/jobs/<id>           status, exit code, log tail
  POST /api/jobs/<id>/stop                 stop a running job (checkpoints let evaluate/noise/parallel resume)
  /                                        frontend/dist (build it with `npm run build`), if present

Usage: cd backend; uv run uvicorn urban.api:app --port 8000
"""
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from urban.data import AREAS, DATA

BACKEND = Path(__file__).resolve().parent.parent
DIST = BACKEND.parent / "frontend" / "dist"
JOBS_DIR = DATA / "jobs"
# step -> what it does (shown in the UI); each is `python -m urban.<step> <area> [args]`
STEPS = {
    "data": "fetch OSM roads, buildings, zones for the area",
    "sim": "build the network and run the micro baseline",
    "candidates": "generate candidate roads",
    "evaluate": "macro screen of all candidates (--workers P)",
    "noise": "micro multi-seed check (--cands 39,27 --workers 2)",
    "parallel": "speedup benchmark (--n 16 --workers 2,4)",
    "isolate": "one-change-at-a-time model tests (--variants ref,zipper)",
    "combos": "greedy search for the best SET of roads (--pool 10 --max 4 --workers 4 --micro-seeds 5)",
    "fcd": "vehicle trajectories for the animation",
    "live": "TomTom real-traffic snapshot (needs TOMTOM_API_KEY)",
    "export": "write the JSON the UI reads",
}
SAFE_DATA = re.compile(r"^([\w-]+/(scenario_stats/)?)?[\w-][\w.-]*\.(geojson|json)$")   # no "..": exported json only
SAFE_ARG = re.compile(r"^[\w.,=-]{1,64}$")   # flags and values only; no shell is involved, this keeps paths out
TAIL = 4000

app = FastAPI(title="Urban planning engine")
jobs: dict[int, dict] = {}
lock = threading.Lock()


class JobIn(BaseModel):
    step: str
    area: str = "hebbal"
    args: list[str] = []


def view(j):
    log = j["log"].read_text(errors="replace")[-TAIL:] if j["log"].exists() else ""
    return {k: j[k] for k in ("id", "step", "area", "args", "status", "returncode", "started", "ended")} | {"log": log}


def watch(j):
    j["returncode"] = j["proc"].wait()
    j["status"] = "stopped" if j["status"] == "stopping" else ("done" if j["returncode"] == 0 else "failed")
    j["ended"] = time.time()


@app.get("/api/steps")
def steps():
    return {"steps": STEPS, "areas": list(AREAS)}


@app.get("/api/jobs")
def list_jobs():
    return [view(j) for j in sorted(jobs.values(), key=lambda j: -j["id"])]


@app.get("/api/jobs/{jid}")
def get_job(jid: int):
    if jid not in jobs:
        raise HTTPException(404, "no such job")
    return view(jobs[jid])


@app.post("/api/jobs", status_code=201)
def start_job(body: JobIn):
    if body.step not in STEPS:
        raise HTTPException(400, f"unknown step; one of {list(STEPS)}")
    if body.area not in AREAS:
        raise HTTPException(400, f"unknown area; one of {list(AREAS)}")
    if not all(SAFE_ARG.match(a) for a in body.args):
        raise HTTPException(400, "arguments may contain only letters, digits and . , = - _")
    with lock:
        busy = [j for j in jobs.values() if j["status"] in ("running", "stopping")]
        if busy:
            raise HTTPException(409, f"job {busy[0]['id']} ({busy[0]['step']}) is still running")
        jid = max(jobs, default=0) + 1
        JOBS_DIR.mkdir(parents=True, exist_ok=True)
        log = JOBS_DIR / f"{jid}_{body.step}.log"
        with open(log, "wb") as f:
            proc = subprocess.Popen([sys.executable, "-u", "-m", f"urban.{body.step}", body.area, *body.args],
                                    cwd=BACKEND, stdout=f, stderr=subprocess.STDOUT)
        j = jobs[jid] = {"id": jid, "step": body.step, "area": body.area, "args": body.args, "status": "running",
                         "returncode": None, "started": time.time(), "ended": None, "proc": proc, "log": log}
    threading.Thread(target=watch, args=(j,), daemon=True).start()
    return view(j)


@app.post("/api/jobs/{jid}/stop")
def stop_job(jid: int):
    j = jobs.get(jid)
    if not j:
        raise HTTPException(404, "no such job")
    if j["status"] == "running":
        j["status"] = "stopping"
        j["proc"].terminate()   # ponytail: kills the python step; its SUMO children end when their pipes close
    return view(j)


@app.get("/data/{path:path}")
def data(path: str):
    f = DATA / path
    if not SAFE_DATA.match(path) or not f.is_file():
        raise HTTPException(404, "not exported yet: run the export step")
    return FileResponse(f, media_type="application/json")


if DIST.exists():   # the built UI; in development use `npm run dev` (Vite proxies /api here)
    app.mount("/", StaticFiles(directory=DIST, html=True), name="ui")
