from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import cv2

from ..config import get_config, PROJECT_ROOT
from ..llm.chat import ask_chain, image_blocks
from ..llm.tracing import langchain_callbacks
from ..plate import normalise_plate, pick_plate, plates_in_texts
from ..runs import append_event, run_dir, write_json_atomic
from langchain_core.messages import HumanMessage, SystemMessage

log = logging.getLogger(__name__)

_running: set[str] = set()
_running_lock = threading.Lock()

_ocr_engine = None
_ocr_lock = threading.Lock()


def try_claim(run_id: str) -> bool:
    with _running_lock:
        if run_id in _running:
            return False
        _running.add(run_id)
        return True


def _get_ocr():
    global _ocr_engine
    with _ocr_lock:
        if _ocr_engine is None:
            try:
                from rapidocr import RapidOCR
                _ocr_engine = RapidOCR()
            except Exception as exc:
                log.warning("RapidOCR not available: %s", exc)
                _ocr_engine = False
        return None if _ocr_engine is False else _ocr_engine


def _validate_verify(parsed: dict) -> str | None:
    if not isinstance(parsed.get("findings"), list):
        return "findings is not a list"
    for f in parsed["findings"]:
        if "item_id" not in f or "confirmed" not in f:
            return "finding missing item_id or confirmed"
    for key in ("badge", "odometer_km", "vehicle", "tyres_assessed", "odometer_found", "plate"):
        if key not in parsed:
            return f"missing key: {key}"
    return None


def run_verify(run_id: str, claimed: bool = False) -> None:
    if not claimed and not try_claim(run_id):
        log.warning("verify already running for %s", run_id)
        return
    try:
        append_event(run_id, "verify", "node_started",
                     {"label": "Reading plate, then asking the verify models"})
        try:
            _run_verify_inner(run_id)
        except Exception as exc:
            log.exception("run_verify unhandled exception for %s", run_id)
            try:
                append_event(run_id, "verify", "node_failed", {"error": f"Unexpected error: {exc}"})
            except Exception:
                pass
    finally:
        with _running_lock:
            _running.discard(run_id)


def _run_verify_inner(run_id: str) -> None:
    rd = run_dir(run_id)
    manifest_path = rd / "02_frames" / "manifest.json"
    if not manifest_path.exists():
        append_event(run_id, "verify", "node_skipped", {"reason": "Frames did not finish"})
        return

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    all_items = [i for i in manifest.get("items", []) if i.get("sharpest")]
    if not all_items:
        append_event(run_id, "verify", "node_skipped", {"reason": "Frames did not finish"})
        return

    frames_dir = rd / "02_frames"
    out_dir = rd / "03_verify"
    out_dir.mkdir(exist_ok=True)

    # --- Plate OCR ---
    plate_items = [i for i in all_items if i.get("category") == "plate"]
    if plate_items:
        ocr_result = _run_ocr(plate_items, frames_dir)
    else:
        ocr_result = {"engine": "rapidocr", "elapsed_s": 0.0, "frames": [], "plate": None}
    write_json_atomic(out_dir / "ocr.json", ocr_result)

    plate_from_ocr = ocr_result.get("plate") is not None
    if plate_from_ocr:
        p = ocr_result["plate"]
        append_event(run_id, "verify", "node_progress",
                     {"message": f"Plate by OCR: {p['text']} ({p['frames_agree']}/{p['frames_tried']} frames)"})
    elif plate_items:
        append_event(run_id, "verify", "node_progress",
                     {"message": "Plate not found by OCR, sending plate frames to the model"})

    # --- Frames to send ---
    send_items = [i for i in all_items if not (plate_from_ocr and i.get("category") == "plate")]
    frame_dicts = [
        {"item_id": i["item_id"], "category": i.get("category", ""),
         "label": i.get("label", ""), "file": i["sharpest"]["file"]}
        for i in send_items
    ]

    # --- Prompts ---
    cfg = get_config()
    prompts_dir = PROJECT_ROOT / cfg.paths.prompts_dir
    system_prompt = (prompts_dir / "verify.system.md").read_text(encoding="utf-8")
    user_prompt = (prompts_dir / "verify.user.md").read_text(encoding="utf-8").format(
        frame_count=len(frame_dicts)
    )

    # --- request.json (written before the call) ---
    request_data = {
        "node": "verify",
        "chain": [{"provider": e.provider, "model": e.model} for e in cfg.models.verify_chain],
        "timeout_per_model_sec": cfg.models.verify_timeout_per_model_sec,
        "plate_from_ocr": plate_from_ocr,
        "system_prompt": system_prompt,
        "user_prompt": user_prompt,
        "media": [
            {"type": "image", "file": f"02_frames/{f['file']}",
             "item_id": f["item_id"], "bytes": (frames_dir / f["file"]).stat().st_size}
            for f in frame_dicts
        ],
        "sent_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    write_json_atomic(out_dir / "request.json", request_data)

    # --- Model chain ---
    cbs = langchain_callbacks(run_id, "verify")

    def build_messages(entry):
        res = cfg.models.verify_media_resolution if entry.provider == "google_genai" else None
        content = image_blocks(user_prompt, frame_dicts, frames_dir, res)
        return [SystemMessage(content=system_prompt), HumanMessage(content=content)]

    chain_result = ask_chain(
        cfg.models.verify_chain,
        build_messages,
        temperature=cfg.models.temperature,
        timeout_sec=cfg.models.verify_timeout_per_model_sec,
        thinking_level=cfg.models.verify_thinking_level,
        validate=_validate_verify,
        emit=lambda msg: append_event(run_id, "verify", "node_progress", {"message": msg}),
        callbacks=cbs,
    )

    # --- response.json ---
    winning = next((a for a in chain_result["attempts"]
                    if "tokens" in a and "error" not in a), None)
    response_data: dict = {
        "received_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "answered_by": chain_result["answered_by"],
        "attempts": chain_result["attempts"],
        "parsed": chain_result["parsed"],
    }
    if winning:
        response_data["tokens"] = winning["tokens"]
        response_data["raw_text"] = winning["raw_text"]
    write_json_atomic(out_dir / "response.json", response_data)

    files = ["03_verify/ocr.json", "03_verify/request.json", "03_verify/response.json"]

    if chain_result["answered_by"] is None:
        errors = "; ".join(
            f"{a['model']}: {a.get('error', 'unknown')}" for a in chain_result["attempts"]
        )
        append_event(run_id, "verify", "node_failed",
                     {"error": f"All verify models failed: {errors}", "files": files})
        return

    # --- Merge OCR plate into parsed ---
    parsed = chain_result["parsed"]
    if plate_from_ocr:
        op = ocr_result["plate"]
        first_frame = next(
            (f["file"] for f in ocr_result.get("frames", []) if f.get("plates")), None
        )
        parsed["plate"] = {
            "text": op["text"],
            "confidence": op["confidence"],
            "alternatives": op["alternatives"],
            "frame": first_frame,
            "source": "ocr",
        }
    elif parsed.get("plate") is not None:
        parsed["plate"]["source"] = "model"

    n_findings = len(parsed.get("findings", []))
    confirmed = sum(1 for f in parsed.get("findings", []) if f.get("confirmed"))
    answered_model = chain_result["answered_by"]["model"]
    plate_text = (parsed.get("plate") or {}).get("text", "none")
    plate_source = (parsed.get("plate") or {}).get("source", "none")

    append_event(run_id, "verify", "packet",
                 {"from": "verify", "to": "confirm", "label": f"{n_findings} findings"})
    append_event(run_id, "verify", "node_done", {
        "summary": (f"{confirmed}/{n_findings} confirmed by {answered_model}, "
                    f"plate {plate_text} ({plate_source})"),
        "files": files,
    })


def _run_ocr(plate_items: list[dict], frames_dir: Path) -> dict:
    t0 = time.perf_counter()
    ocr = _get_ocr()
    frames_data = []
    readings: list[tuple[str, float]] = []

    for item in plate_items:
        file = item["sharpest"]["file"]
        frame_rec: dict = {"item_id": item["item_id"], "file": file,
                           "seconds": 0.0, "texts": [], "plates": []}
        if ocr is not None:
            try:
                img = cv2.imread(str(frames_dir / file))
                tf = time.perf_counter()
                out = ocr(img)
                frame_rec["seconds"] = round(time.perf_counter() - tf, 2)
                texts = []
                if out and out.txts:
                    for text, score in zip(out.txts, out.scores):
                        texts.append({"text": text, "score": round(float(score), 3)})
                frame_rec["texts"] = texts
                raw_texts = [x["text"] for x in texts]
                plate_matches = plates_in_texts(raw_texts)
                frame_rec["plates"] = plate_matches
                if plate_matches:
                    best_text, best_score = max(
                        ((x["text"], x["score"]) for x in texts
                         if normalise_plate(x["text"]) in plate_matches),
                        key=lambda r: r[1],
                    )
                    readings.append((normalise_plate(best_text), best_score))
            except Exception as exc:
                log.warning("OCR failed for %s: %s", file, exc)
        frames_data.append(frame_rec)

    return {
        "engine": "rapidocr",
        "elapsed_s": round(time.perf_counter() - t0, 2),
        "frames": frames_data,
        "plate": pick_plate(readings, len(plate_items)),
    }
