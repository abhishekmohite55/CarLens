"""Does the video show the VIN's car? (owner, 27 Nov 2026). Pure: the caller passes every value.

Verify answers vin_match {result: match | mismatch | unsure, confidence, reason, frame} in its one call. Only a
confident mismatch counts; the action (stop / warn) comes from config. It can catch a different car (brand, model,
body); it cannot prove the very same car of an identical model."""
from __future__ import annotations

from typing import Any, Mapping

RESULTS = ("match", "mismatch", "unsure")
ACTIONS = ("stop", "warn")


def car_line(car: Mapping[str, Any] | None) -> str:
    """"2003 HONDA Accord EX-V6, Coupe, 3.0L V6, Gasoline" for the verify prompt and messages."""
    car = car or {}
    name = " ".join(str(car[k]) for k in ("year", "make", "model", "variant") if car.get(k))
    rest = ", ".join(str(car[k]) for k in ("body", "engine", "fuel") if car.get(k))
    return ", ".join(p for p in (name, rest) if p) or "unknown car"


def vin_match_verdict(answer: Mapping[str, Any] | None, action: str, min_confidence: float) -> dict:
    """{result, confidence, reason, frame, counted, action: stop | warn | none}. counted = a mismatch at
    confidence >= min_confidence; action is "none" unless counted."""
    a = answer if isinstance(answer, Mapping) else {}
    result = str(a.get("result") or "").strip().lower()
    result = result if result in RESULTS else "unsure"
    try:
        conf = float(a.get("confidence")) if a.get("confidence") is not None else None
    except (TypeError, ValueError):
        conf = None
    counted = result == "mismatch" and conf is not None and conf >= min_confidence
    return {"result": result, "confidence": conf, "reason": a.get("reason"), "frame": a.get("frame"),
            "counted": counted, "action": (action if action in ACTIONS else "stop") if counted else "none"}


def mismatch_message(car: Mapping[str, Any] | None, reason: str | None) -> str:
    because = f": {reason.rstrip('.')}" if reason else ""
    return (f"The video does not look like the car of this VIN ({car_line(car)}){because}. "
            "Check the VIN or the video, then start a new run.")
