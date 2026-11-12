"""Photos node (Stage 6): reads the extra tyre/odometer photos added at confirm with the photos model chain.
Saves request.json, response.json, applied.json (what plan and extract use) in the database; JPEGs stay in 05_photos/. Skipped without photos."""
from __future__ import annotations

import io
import logging
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np
from langchain_core.messages import HumanMessage, SystemMessage

from ..config import get_config, pinned
from ..settings_store import load_prompt
from ..frames import save_jpeg
from ..llm.chat import ask_chain, image_blocks
from ..llm.tracing import langchain_callbacks
from ..photos import apply_photos, list_photos, validate_answer
from ..results import load_result, save_result
from ..runs import append_event, run_dir
from .confirm import load_record, load_verify_answer

log = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def save_photo(folder: Path, slot: str, filename: str, data: bytes) -> str | None:
    """Check type, size and that it decodes; save as <slot>.jpg (frames size and quality). Returns a problem or None."""
    p, f = get_config().photos, get_config().frames
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in p.allowed_types:
        return f"Only {', '.join(p.allowed_types)} photos are accepted."
    if len(data) > p.max_size_mb * 1024 * 1024:
        return f"Photo is over {p.max_size_mb} MB."
    img = _decode_heic(data) if ext == "heic" else cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return "This file could not be read as an image."
    folder.mkdir(parents=True, exist_ok=True)
    save_jpeg(img, folder / f"{slot}.jpg", f.max_long_edge_px, f.jpeg_quality)
    return None


def _decode_heic(data: bytes):
    """iPhone HEIC to an OpenCV image (OpenCV cannot read HEIC). None if it does not decode."""
    try:
        from PIL import Image
        from pillow_heif import register_heif_opener
        register_heif_opener()
        rgb = Image.open(io.BytesIO(data)).convert("RGB")
        return cv2.cvtColor(np.array(rgb), cv2.COLOR_RGB2BGR)
    except Exception as exc:
        log.warning("HEIC decode failed: %s", exc)
        return None


def load_photos_answer(run_id: str) -> dict | None:
    """The photos model answer, or None (no photos, or every model failed)."""
    data = load_result(run_id, "05_photos/response.json")
    if data is None:
        return None
    return data.get("parsed") if data.get("answered_by") else None


@pinned
def run_photos(run_id: str) -> None:
    try:
        _run_photos_inner(run_id)
    except Exception as exc:
        log.exception("run_photos failed for %s", run_id)
        append_event(run_id, "photos", "node_failed", {"error": f"Unexpected error: {exc}"})


def _run_photos_inner(run_id: str) -> None:
    rd = run_dir(run_id)
    out = rd / "05_photos"
    photos = list_photos(out)
    if not photos:
        append_event(run_id, "photos", "node_skipped", {"reason": "No photos uploaded"})
        return
    append_event(run_id, "photos", "node_started", {"label": f"Reading {len(photos)} extra photo(s)"})
    cfg = get_config()
    chain = cfg.models.photos_chain or cfg.models.verify_chain
    system_prompt = load_prompt("photos.system.md")
    user_prompt = load_prompt("photos.user.md").format(photo_count=len(photos))
    frames = [{"file": f"{p['slot']}.jpg", "item_id": p["slot"],
               "category": "odometer" if p["slot"] == "odometer" else "tyre",
               "label": "odometer" if p["slot"] == "odometer" else p["slot"].replace("_", " ") + " tyre"} for p in photos]
    save_result(run_id, "05_photos/request.json", {
        "node": "photos", "chain": [{"provider": e.provider, "model": e.model} for e in chain],
        "timeout_per_model_sec": cfg.models.photos_timeout_per_model_sec,
        "system_prompt": system_prompt, "user_prompt": user_prompt,
        "media": [{"type": "image", "file": p["file"], "slot": p["slot"], "bytes": (rd / p["file"]).stat().st_size}
                  for p in photos],
        "sent_at": _now()})
    files = ["05_photos/request.json"]

    def build_messages(entry):
        res = cfg.models.verify_media_resolution if entry.provider == "google_genai" else None
        return [SystemMessage(content=system_prompt), HumanMessage(content=image_blocks(user_prompt, frames, out, res))]

    answer = ask_chain(chain, build_messages, temperature=cfg.models.temperature,
                       timeout_sec=cfg.models.photos_timeout_per_model_sec, thinking_level=cfg.models.verify_thinking_level,
                       validate=validate_answer,
                       emit=lambda msg: append_event(run_id, "photos", "node_progress", {"message": msg}),
                       callbacks=langchain_callbacks(run_id, "photos"),
                       metadata={"langfuse_session_id": run_id, "langfuse_trace_name": "photos"})
    save_result(run_id, "05_photos/response.json", {"received_at": _now(), **answer})
    files.append("05_photos/response.json")
    if answer["parsed"] is None:  # plan and extract then use verify + confirm as they are
        append_event(run_id, "photos", "node_failed",
                     {"error": "Every photos model failed; the video results are used", "files": files})
        return

    confirm = load_record(run_id)
    findings = (load_verify_answer(run_id) or {}).get("findings") or []
    _, _, applied = apply_photos(confirm, findings, answer["parsed"], cfg.photos.km_min_confidence)
    save_result(run_id, "05_photos/applied.json", applied)  # also fills photo_results (JPEGs stay in 05_photos/)
    files.append("05_photos/applied.json")
    km = applied["km"]
    parts = ([f"{len(applied['tyres_replaced'])} tyre(s) replaced", f"{len(applied['tyres_added'])} added"]
             + ([f"km {km['photo_km']:,} ({km['confidence']}, {'used' if km['used'] else 'not used: low confidence'})"]
                if km else []))
    append_event(run_id, "photos", "packet", {"from": "photos", "to": "plan", "label": f"{len(photos)} photo(s) read"})
    append_event(run_id, "photos", "node_done",
                 {"summary": f"{', '.join(parts)}; by {answer['answered_by']['model']}", "files": files})
