from __future__ import annotations

import json
import threading
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse

from .config import get_config
from .events import sse_stream
from .graph import run_graph
from .llm.tracing import _get_client as _warmup_tracing
from .nodes.upload import process_upload
from .runs import events_path, run_dir

# run_ids that have started or are starting the graph
_started: set[str] = set()
_start_lock = threading.Lock()

app = FastAPI(title="CarLens backend")


@app.on_event("startup")
def _startup():
    _warmup_tracing()


app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_INSPECTOR = Path(__file__).parent.parent / "inspector" / "index.html"

# Node list — ids and labels from 02-design.md §3.2
_NODES = [
    {"id": "upload",  "label": "Upload & check"},
    {"id": "locate",  "label": "Locate (Gemini)"},
    {"id": "frames",  "label": "Extract frames"},
    {"id": "verify",  "label": "Verify (Gemini)"},
    {"id": "confirm", "label": "You confirm"},
    {"id": "photos",  "label": "Extra photos (Gemini)"},
    {"id": "plan",    "label": "Plan searches (LLM)"},
    {"id": "search",  "label": "Search web (Tavily)"},
    {"id": "extract", "label": "Read prices (LLM)"},
    {"id": "pricing", "label": "Price & report"},
]


@app.get("/api/config")
def api_config():
    cfg = get_config()
    return {
        "upload": {
            "allowed_types": cfg.upload.allowed_types,
            "max_size_mb": cfg.upload.max_size_mb,
            "max_duration_sec": cfg.upload.max_duration_sec,
        },
        "nodes": _NODES,
    }


@app.post("/api/runs")
async def api_create_run(video: UploadFile = File(...)):
    return await process_upload(video)


@app.get("/api/runs/{run_id}")
def api_get_run(run_id: str):
    rd = run_dir(run_id)
    if not rd.exists():
        raise HTTPException(404, detail=f"Run '{run_id}' not found.")

    meta_path = rd / "meta.json"
    meta: dict = {}
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))

    node_status: dict[str, str] = {n["id"]: "waiting" for n in _NODES}
    ev_path = rd / "events.jsonl"
    if ev_path.exists():
        with open(ev_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                node = ev.get("node", "")
                etype = ev.get("type", "")
                if node not in node_status:
                    continue
                if etype == "node_started" and node_status[node] == "waiting":
                    node_status[node] = "running"
                elif etype == "node_done":
                    node_status[node] = "done"
                elif etype == "node_failed":
                    node_status[node] = "failed"
                elif etype == "node_skipped":
                    node_status[node] = "skipped"

    return {"run_id": run_id, "meta": meta, "nodes": node_status}


def _has_locate_event(run_id: str) -> bool:
    ep = events_path(run_id)
    if not ep.exists():
        return False
    with open(ep, encoding="utf-8") as f:
        for line in f:
            try:
                ev = json.loads(line)
                if ev.get("node") == "locate":
                    return True
            except json.JSONDecodeError:
                pass
    return False


@app.get("/api/runs/{run_id}/events")
async def api_run_events(run_id: str):
    rd = run_dir(run_id)
    if not rd.exists():
        raise HTTPException(404, detail=f"Run '{run_id}' not found.")

    with _start_lock:
        if run_id not in _started and not _has_locate_event(run_id):
            _started.add(run_id)
            t = threading.Thread(target=run_graph, args=(run_id,), daemon=True)
            t.start()

    return StreamingResponse(
        sse_stream(run_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/runs/{run_id}/files/{path:path}")
def api_run_file(run_id: str, path: str):
    rd = run_dir(run_id)
    if not rd.exists():
        raise HTTPException(404, detail=f"Run '{run_id}' not found.")

    try:
        target = (rd / path).resolve()
        base = rd.resolve()
        target.relative_to(base)  # raises ValueError if outside base
    except ValueError:
        raise HTTPException(400, detail="Path is outside the run folder.")
    except Exception:
        raise HTTPException(400, detail="Invalid path.")

    if target.is_symlink():
        raise HTTPException(400, detail="Symlinks are not served.")

    if not target.exists():
        raise HTTPException(404, detail=f"File not found: {path}")

    return FileResponse(target)


@app.get("/inspector")
def inspector():
    return FileResponse(_INSPECTOR)
