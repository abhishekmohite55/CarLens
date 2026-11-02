from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from ..config import PROJECT_ROOT, get_config
from ..llm.gemini_video import call_gemini_video
from ..llm.tracing import trace_locate
from ..runs import append_event, run_dir, write_json_atomic
from ..timecode import mmss_to_seconds, seconds_to_mmss
from ..video import shrink_video

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
                    "t":        {"type": "string"},
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


def _validate_locate_items(items: list, duration_sec: float) -> list:
    """Validate and return a copy of items; clamps t up to 1 s past duration."""
    validated = []
    for item in items:
        item = dict(item)
        if item.get("category") not in _CATEGORIES:
            raise ValueError(f"unknown category: {item.get('category')!r}")
        if item.get("side") not in _SIDES:
            raise ValueError(f"unknown side: {item.get('side')!r}")
        t_text = item.get("t")
        try:
            t = mmss_to_seconds(t_text)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"item {item.get('id')!r}: bad t={t_text!r}: {exc}") from exc
        if t < 0 or t > duration_sec + 1:
            raise ValueError(f"t={t!r} out of range [0, {duration_sec + 1}]")
        item["t_text"] = t_text
        item["t"] = t
        if t > duration_sec:
            item["t"] = duration_sec
            item["t_clamped"] = True
        validated.append(item)
    return validated


def _read_prompt(name: str) -> str:
    cfg = get_config()
    path = PROJECT_ROOT / cfg.paths.prompts_dir / name
    return path.read_text(encoding="utf-8")


def run_locate(run_id: str) -> None:
    append_event(run_id, "locate", "node_started", {"label": "Asking Gemini to locate items"})
    try:
        _run_locate_inner(run_id)
    except Exception as exc:
        log.exception("run_locate unhandled exception for %s", run_id)
        try:
            append_event(run_id, "locate", "node_failed", {"error": f"Unexpected error: {exc}"})
        except Exception:
            pass


def _run_locate_inner(run_id: str) -> None:
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
    user_prompt = (
        _read_prompt("locate.user.md")
        .replace("{duration_sec}", str(duration_sec))
        .replace("{duration_mmss}", seconds_to_mmss(duration_sec))
    )

    out_dir = rd / "01_locate"
    out_dir.mkdir(exist_ok=True)

    # Shrink video if configured; fall back to original on error
    lv = cfg.locate_video
    send_path = video_path
    shrink_settings: dict | None = None
    if lv.shrink:
        small_path = out_dir / "video_small.mp4"
        try:
            emit_fn_tmp = lambda msg: append_event(run_id, "locate", "node_progress", {"message": msg})
            emit_fn_tmp("Shrinking video")
            shrink_video(video_path, small_path, height=lv.height, fps=lv.fps, crf=lv.crf)
            send_path = small_path
            shrink_settings = {"height": lv.height, "fps": lv.fps, "crf": lv.crf}
        except Exception as exc:
            log.warning("shrink failed for %s: %s — sending original", run_id, exc)
            emit_fn_tmp("Shrink failed, sending original video")

    sent_file = send_path.relative_to(rd).as_posix()
    sent_mb = round(send_path.stat().st_size / 1e6, 1)

    # Write request.json (gemini_file filled in after call)
    request_data = {
        "node": "locate",
        "model": cfg.models.locate.model,
        "settings": {
            "media_resolution": cfg.models.locate_media_resolution,
            "temperature": cfg.models.temperature,
            "thinking_level": cfg.models.locate_thinking_level,
            "shrink": shrink_settings,
        },
        "system_prompt": system_prompt,
        "user_prompt": user_prompt,
        "media": [{
            "type": "video",
            "file": sent_file,
            "source_file": video_path.name,
            "size_mb": sent_mb,
            "gemini_file": None,
        }],
        "sent_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    write_json_atomic(out_dir / "request.json", request_data)

    def emit(msg: str) -> None:
        append_event(run_id, "locate", "node_progress", {"message": msg})

    try:
        result = call_gemini_video(
            video_path=send_path,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=cfg.models.locate.model,
            fallback_model=cfg.models.locate.fallback_model,
            temperature=cfg.models.temperature,
            media_resolution=cfg.models.locate_media_resolution,
            timeout_sec=cfg.models.timeout_sec,
            emit=emit,
            response_schema=_RESPONSE_SCHEMA,
            thinking_level=cfg.models.locate_thinking_level,
        )
    except Exception as exc:
        log.exception("locate gemini call failed for %s", run_id)
        append_event(run_id, "locate", "node_failed", {
            "error": str(exc),
            "files": ["01_locate/request.json"],
        })
        return

    model_used = result.get("model_used", cfg.models.locate.model)

    try:
        # Update request.json with gemini_file, actual model, fallback block if used
        request_data["media"][0]["gemini_file"] = result["gemini_file_name"]
        request_data["model"] = model_used
        if "fallback" in result:
            request_data["fallback"] = result["fallback"]
        write_json_atomic(out_dir / "request.json", request_data)
    except Exception as exc:
        log.exception("Failed to update request.json for %s", run_id)

    # Trace to Langfuse (record the model that actually answered)
    trace_locate(
        run_id=run_id,
        model=model_used,
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
        parsed["items"] = _validate_locate_items(parsed["items"], duration_sec)
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
