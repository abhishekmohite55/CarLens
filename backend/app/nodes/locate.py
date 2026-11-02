from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from ..config import PROJECT_ROOT, get_config
from ..llm.gemini_video import call_gemini_video
from ..llm.tracing import trace_locate
from ..runs import append_event, run_dir, write_json_atomic

log = logging.getLogger(__name__)

_CATEGORIES = {"plate", "model_badge", "odometer", "damage", "mirror", "tyre", "windshield"}
_SIDES = {"front", "rear", "left", "right", "roof", "interior"}

_RESPONSE_SCHEMA = {
    "type": "object",
    "required": ["items", "coverage"],
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["id", "category", "label", "side", "t"],
                "properties": {
                    "id":       {"type": "string"},
                    "category": {"type": "string", "enum": sorted(_CATEGORIES)},
                    "label":    {"type": "string"},
                    "side":     {"type": "string", "enum": sorted(_SIDES)},
                    "t":        {"type": "number"},
                },
            },
        },
        "coverage": {
            "type": "object",
            "properties": {
                "front":    {"type": "boolean"},
                "rear":     {"type": "boolean"},
                "left":     {"type": "boolean"},
                "right":    {"type": "boolean"},
                "roof":     {"type": "boolean"},
                "interior": {"type": "boolean"},
            },
        },
    },
}


def _read_prompt(name: str) -> str:
    cfg = get_config()
    path = PROJECT_ROOT / cfg.paths.prompts_dir / name
    return path.read_text(encoding="utf-8")


def run_locate(run_id: str) -> None:
    append_event(run_id, "locate", "node_started", {"label": "Asking Gemini to locate items"})

    rd = run_dir(run_id)
    meta = json.loads((rd / "meta.json").read_text(encoding="utf-8"))
    duration_sec = meta["duration_sec"]

    # Find video file
    video_path: Path | None = None
    for ext in ("mp4", "mov", "webm"):
        p = rd / f"video.{ext}"
        if p.exists():
            video_path = p
            break
    if video_path is None:
        append_event(run_id, "locate", "node_failed", {"error": "Video file not found in run folder."})
        return

    cfg = get_config()
    system_prompt = _read_prompt("locate.system.md")
    user_prompt = _read_prompt("locate.user.md").replace("{duration_sec}", str(duration_sec))

    out_dir = rd / "01_locate"
    out_dir.mkdir(exist_ok=True)

    # Write request.json (gemini_file filled in after upload)
    request_data = {
        "node": "locate",
        "model": cfg.models.locate.model,
        "settings": {
            "media_resolution": cfg.models.locate_media_resolution,
            "temperature": cfg.models.temperature,
        },
        "system_prompt": system_prompt,
        "user_prompt": user_prompt,
        "media": [{"type": "video", "file": video_path.name, "gemini_file": None}],
        "sent_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    write_json_atomic(out_dir / "request.json", request_data)

    def emit(msg: str) -> None:
        append_event(run_id, "locate", "node_progress", {"message": msg})

    try:
        result = call_gemini_video(
            video_path=video_path,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=cfg.models.locate.model,
            temperature=cfg.models.temperature,
            media_resolution=cfg.models.locate_media_resolution,
            timeout_sec=cfg.models.timeout_sec,
            emit=emit,
            response_schema=_RESPONSE_SCHEMA,
        )
    except Exception as exc:
        log.exception("locate gemini call failed for %s", run_id)
        append_event(run_id, "locate", "node_failed", {
            "error": str(exc),
            "files": ["01_locate/request.json"],
        })
        return

    # Update request.json with gemini_file name
    request_data["media"][0]["gemini_file"] = result["gemini_file_name"]
    write_json_atomic(out_dir / "request.json", request_data)

    # Trace to Langfuse
    trace_locate(
        run_id=run_id,
        model=cfg.models.locate.model,
        request_data=request_data,
        raw_text=result["raw_text"],
        tokens=result["tokens"],
    )

    # Parse and validate
    raw_text = result["raw_text"]
    parsed = None
    fail_reason: str | None = None

    try:
        parsed = json.loads(raw_text)
        if not isinstance(parsed, dict):
            raise ValueError("top-level JSON is not an object")
        if "items" not in parsed or "coverage" not in parsed:
            raise ValueError("missing 'items' or 'coverage' key")
        for item in parsed["items"]:
            if item.get("category") not in _CATEGORIES:
                raise ValueError(f"unknown category: {item.get('category')!r}")
            if item.get("side") not in _SIDES:
                raise ValueError(f"unknown side: {item.get('side')!r}")
            t = item.get("t")
            if not isinstance(t, (int, float)) or t < 0 or t > duration_sec:
                raise ValueError(f"t={t!r} out of range [0, {duration_sec}]")
    except Exception as exc:
        fail_reason = str(exc)
        parsed = None

    # Write response.json
    write_json_atomic(out_dir / "response.json", {
        "received_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "duration_ms": result["duration_ms"],
        "tokens": result["tokens"],
        "raw_text": raw_text,
        "parsed": parsed,
    })

    files = ["01_locate/request.json", "01_locate/response.json"]

    if fail_reason:
        append_event(run_id, "locate", "node_failed", {
            "error": f"Invalid locate response: {fail_reason}",
            "files": files,
        })
        return

    n = len(parsed["items"])
    append_event(run_id, "locate", "packet", {
        "from": "locate",
        "to": "frames",
        "label": f"{n} timestamps",
    })
    append_event(run_id, "locate", "node_done", {
        "summary": f"{n} timestamps found",
        "files": files,
    })
