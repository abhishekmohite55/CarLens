from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import cv2

from ..config import current_market, get_config, market_config, pinned
from ..miles import miles_used
from ..vin.match import car_line, mismatch_message, vin_match_verdict
from ..settings_store import load_prompt
from ..llm.chat import ask_chain, image_blocks
from ..llm.tracing import langchain_callbacks
from ..plate import normalise_plate, pick_plate, plates_in_texts
from ..results import load_result, save_result
from ..runs import append_event, run_dir
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


_ANSWER_KEYS = ("plate", "badge", "odometer_km", "vehicle", "tyres_assessed", "odometer_found")
_OBJECT_KEYS = ("plate", "badge", "odometer_km", "vehicle")
_VEHICLE_FIELDS = ("make", "model", "variant", "year", "fuel")


def normalise_answer(parsed):
    """Repair known shape slips of model answers (key names and wrapping only, never values).

    Returns (answer, repairs). A well-formed answer comes back unchanged with no repairs.
    Shapes it cannot repair are left for validate_answer to reject.
    """
    repairs: list[str] = []
    if isinstance(parsed, list):
        parsed = {"findings": parsed}
        repairs.append("answer was a list: used as findings")
    if not isinstance(parsed, dict):
        return parsed, repairs

    for key in ("plate", "badge"):
        v = parsed.get(key)
        if isinstance(v, str):
            parsed[key] = {"text": v, "confidence": None}
            repairs.append(f"{key} was text: wrapped as {{text}}")
        elif isinstance(v, dict) and "text" not in v and "value" in v:
            v["text"] = v.pop("value")
            repairs.append(f"{key}.value renamed to {key}.text")

    odo = parsed.get("odometer_km")
    if isinstance(odo, (int, float)) and not isinstance(odo, bool):
        parsed["odometer_km"] = {"value": odo, "confidence": None}
        repairs.append("odometer_km was a number: wrapped as {value}")
    elif isinstance(odo, dict) and "value" not in odo and "text" in odo:
        odo["value"] = odo.pop("text")
        repairs.append("odometer_km.text renamed to odometer_km.value")

    vehicle = parsed.get("vehicle")
    if isinstance(vehicle, dict):
        for field in _VEHICLE_FIELDS:
            v = vehicle.get(field)
            if v is not None and not isinstance(v, dict):
                vehicle[field] = {"value": v, "confidence": None, "alternatives": []}
                repairs.append(f"vehicle.{field} was a bare value: wrapped as {{value}}")

    for key in _OBJECT_KEYS:
        if parsed.get(key) is not None and not isinstance(parsed[key], dict):
            parsed[key] = None
            repairs.append(f"{key} had an unknown shape: set to null")

    for key in _ANSWER_KEYS:
        if key not in parsed:
            parsed[key] = None
            repairs.append(f"{key} missing: set to null")

    _keep_findings(parsed, repairs)
    return parsed, repairs


def _keep_findings(parsed: dict, repairs: list[str]) -> None:
    findings = parsed.get("findings")
    if isinstance(findings, list):
        kept = [f for f in findings if isinstance(f, dict) and "item_id" in f and "confirmed" in f]
        if len(kept) != len(findings):
            repairs.append(f"{len(findings) - len(kept)} finding(s) without item_id/confirmed dropped")
            parsed["findings"] = kept


# Stage U3: the US answer has no plate, badge or vehicle (the car comes from the VIN); the odometer has a unit.
_US_ANSWER_KEYS = ("odometer", "tyres_assessed", "odometer_found", "vin_match")
_UNITS = {"mi": "mi", "mile": "mi", "miles": "mi", "km": "km", "kms": "km", "kilometer": "km", "kilometers": "km",
          "kilometre": "km", "kilometres": "km"}


def normalise_us_answer(parsed):
    """normalise_answer for the US verify answer: findings as for India; odometer {value, unit mi | km, confidence,
    frame}. Key names and wrapping only, never values. Returns (answer, repairs)."""
    repairs: list[str] = []
    if isinstance(parsed, list):
        parsed = {"findings": parsed}
        repairs.append("answer was a list: used as findings")
    if not isinstance(parsed, dict):
        return parsed, repairs
    odo = parsed.get("odometer")
    if isinstance(odo, (int, float)) and not isinstance(odo, bool):
        parsed["odometer"] = odo = {"value": odo, "unit": None, "confidence": None}
        repairs.append("odometer was a number: wrapped as {value}")
    if isinstance(odo, dict):
        if "value" not in odo and "text" in odo:
            odo["value"] = odo.pop("text")
            repairs.append("odometer.text renamed to odometer.value")
        unit = _UNITS.get(str(odo.get("unit") or "").strip().lower())
        if unit != odo.get("unit"):
            repairs.append(f"odometer.unit {odo.get('unit')!r} read as {unit!r}")
            odo["unit"] = unit
    elif odo is not None:
        parsed["odometer"] = None
        repairs.append("odometer had an unknown shape: set to null")
    match = parsed.get("vin_match")
    if isinstance(match, str):
        parsed["vin_match"] = {"result": match, "confidence": None}
        repairs.append("vin_match was text: wrapped as {result}")
    elif match is not None and not isinstance(match, dict):
        parsed["vin_match"] = None
        repairs.append("vin_match had an unknown shape: set to null")
    for key in _US_ANSWER_KEYS:
        if key not in parsed:
            parsed[key] = None
            repairs.append(f"{key} missing: set to null")
    _keep_findings(parsed, repairs)
    return parsed, repairs


def validate_answer(parsed) -> str | None:
    """Reject only what normalise_answer could not repair."""
    if not isinstance(parsed, dict):
        return "answer is not a JSON object"
    if not isinstance(parsed.get("findings"), list):
        return "findings is missing or not a list"
    return None


@pinned
def run_verify(run_id: str, claimed: bool = False) -> None:
    if not claimed and not try_claim(run_id):
        log.warning("verify already running for %s", run_id)
        return
    try:
        label = ("Asking the verify models (US: no plate)" if current_market() == "us"
                 else "Reading plate, then asking the verify models")
        append_event(run_id, "verify", "node_started", {"label": label})
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
    manifest = load_result(run_id, "02_frames/manifest.json")
    if manifest is None:
        append_event(run_id, "verify", "node_skipped", {"reason": "Frames did not finish"})
        return

    all_items = [i for i in manifest.get("items", []) if i.get("sharpest")]
    if not all_items:
        append_event(run_id, "verify", "node_skipped", {"reason": "Frames did not finish"})
        return

    frames_dir = rd / "02_frames"
    us = current_market() == "us"  # stage U3: no plate, no OCR, odometer with its unit, miles rule
    # --- Plate OCR ---
    plate_items = [] if us else [i for i in all_items if i.get("category") == "plate"]
    if plate_items:
        ocr_result = _run_ocr(plate_items, frames_dir)
    else:
        ocr_result = {"engine": "rapidocr", "elapsed_s": 0.0, "frames": [], "plate": None}
    save_result(run_id, "03_verify/ocr.json", ocr_result)

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
    frame_dicts = [f for i in send_items for f in item_frames(i)]  # owner 27 Nov: up to 3 per damage item

    # --- Prompts ---
    cfg = get_config()
    system_prompt = load_prompt("verify.system.md")
    vin_car = car_line((load_result(run_id, "04_confirm.json") or {}).get("car")) if us else ""
    user_prompt = load_prompt("verify.user.md").format(  # India's prompt has no {vin_car}: ignored there
        frame_count=len(frame_dicts), vin_car=vin_car
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
    save_result(run_id, "03_verify/request.json", request_data)

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
        validate=validate_answer,
        normalise=normalise_us_answer if us else normalise_answer,
        emit=lambda msg: append_event(run_id, "verify", "node_progress", {"message": msg}),
        callbacks=cbs,
        metadata={"langfuse_session_id": run_id, "langfuse_trace_name": "verify"},
        max_in_flight=cfg.models.max_calls_in_flight,
    )

    # --- Merge OCR plate into parsed (before response.json, so the saved answer has it) ---
    parsed = chain_result["parsed"]
    if parsed is not None:
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
    save_result(run_id, "03_verify/response.json", response_data)  # also fills verify_findings, verify_vehicle

    files = ["03_verify/ocr.json", "03_verify/request.json", "03_verify/response.json"]

    if chain_result["answered_by"] is None:
        errors = "; ".join(
            f"{a['model']}: {a.get('error', 'unknown')}" for a in chain_result["attempts"]
        )
        append_event(run_id, "verify", "node_failed",
                     {"error": f"All verify models failed: {errors}", "files": files})
        return

    n_findings = len(parsed.get("findings", []))
    confirmed = sum(1 for f in parsed.get("findings", []) if f.get("confirmed"))
    answered_model = chain_result["answered_by"]["model"]
    if us:
        _finish_us(run_id, parsed, files, confirmed, n_findings, answered_model)
        return
    plate_text = (parsed.get("plate") or {}).get("text", "none")
    plate_source = (parsed.get("plate") or {}).get("source", "none")

    append_event(run_id, "verify", "packet",
                 {"from": "verify", "to": "confirm", "label": f"{n_findings} findings"})
    append_event(run_id, "verify", "node_done", {
        "summary": (f"{confirmed}/{n_findings} confirmed by {answered_model}, "
                    f"plate {plate_text} ({plate_source})"),
        "files": files,
    })


_KIND_NOTE = {"locate": "the moment it was found", "angle": "another angle"}


def item_frames(item: dict) -> list[dict]:
    """Frames verify gets for one manifest item: its sharpest, then its extra frames (owner 27 Nov: locate's own
    moment, another angle), each labelled with what it is. A file is never sent twice."""
    base = {"item_id": item["item_id"], "category": item.get("category", ""), "label": item.get("label", "")}
    extra = [x for x in item.get("extra") or [] if x.get("file")]
    first = {**base, "file": item["sharpest"]["file"]}
    if extra:
        first["label"] = f"{base['label']} (sharpest)"
    out, seen = [first], {first["file"]}
    for x in extra:
        if x["file"] not in seen:
            seen.add(x["file"])
            out.append({**base, "label": f"{base['label']} ({_KIND_NOTE.get(x.get('kind'), x.get('kind'))})",
                        "file": x["file"]})
    return out


def _finish_us(run_id: str, parsed: dict, files: list[str], confirmed: int, n_findings: int, model: str) -> None:
    """Stage U3: the miles rule (03_verify/miles.json, read by pricing), then the video-vs-VIN check
    (03_verify/vin_match.json; owner 27 Nov), then node_done — or node_failed (code vin_mismatch) when a confident
    mismatch must stop the run before any search cost. Packet goes to plan."""
    confirm = load_result(run_id, "04_confirm.json") or {}
    us_cfg = market_config()
    odo = parsed.get("odometer") or {}
    result = miles_used(int(confirm.get("miles_user") or 0), odo.get("value"), odo.get("unit"), odo.get("confidence"),
                        us_cfg.odometer_min_confidence)
    save_result(run_id, "03_verify/miles.json", result)
    files.append("03_verify/miles.json")
    other = (f"; you typed {result['miles_user']:,}" if result["source"] == "odometer"
             else f"; odometer {result['reading_miles']:,} mi" if result["reading_miles"] is not None else "")
    append_event(run_id, "verify", "node_progress",
                 {"message": f"Miles used: {result['miles_used']:,} ({result['source']}{other}; {result['why']})"})
    verdict = vin_match_verdict(parsed.get("vin_match"), us_cfg.vin_mismatch_action,
                                us_cfg.vin_mismatch_min_confidence)
    save_result(run_id, "03_verify/vin_match.json", {**verdict, "vin": confirm.get("vin"), "car": confirm.get("car")})
    files.append("03_verify/vin_match.json")
    conf = f"{verdict['confidence']:.2f}" if verdict["confidence"] is not None else "?"
    append_event(run_id, "verify", "node_progress", {"message":
                 f"Video vs VIN ({car_line(confirm.get('car'))}): {verdict['result']} ({conf})"
                 + (f" — {verdict['reason']}" if verdict.get("reason") else "")})
    if verdict["action"] == "stop":
        append_event(run_id, "verify", "node_failed", {"error": mismatch_message(confirm.get("car"), verdict["reason"]),
                                                       "code": "vin_mismatch", "files": files})
        return
    if verdict["action"] == "warn":
        append_event(run_id, "verify", "node_progress",
                     {"message": "Warning: the video may not show the VIN's car; the run goes on (vin_mismatch_action: warn)"})
    reading = f"{odo.get('value')} {odo.get('unit') or '?'}" if odo.get("value") is not None else "not read"
    append_event(run_id, "verify", "packet", {"from": "verify", "to": "plan", "label": f"{n_findings} findings"})
    append_event(run_id, "verify", "node_done", {
        "summary": f"{confirmed}/{n_findings} confirmed by {model}, odometer {reading}, miles used {result['miles_used']:,}",
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
