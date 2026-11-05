"""Extra photos (Stage 6): slots, answer check, and merging the photos answer into confirm + verify findings. Pure
except list_photos (looks at a folder). Merging never writes files: plan and extract call apply_photos on the fly."""
from __future__ import annotations

from pathlib import Path

TYRE_SLOTS = ("front_left", "front_right", "rear_left", "rear_right")
SLOTS = TYRE_SLOTS + ("odometer",)


def list_photos(folder: Path) -> list[dict]:
    """Uploaded photos in slot order, as listed in 04_confirm.json."""
    return [{"slot": s, "file": f"05_photos/{s}.jpg"} for s in SLOTS if (folder / f"{s}.jpg").exists()]


def validate_answer(parsed) -> str | None:
    return None if isinstance(parsed, dict) and isinstance(parsed.get("photos"), list) else "answer has no photos list"


def _number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def apply_photos(confirm: dict, findings: list[dict], answer: dict | None,
                 km_min_confidence: float) -> tuple[dict, list[dict], dict]:
    """Return (confirm, findings, applied). No answer = inputs returned as they are.
    Tyre photo with a score or tread: replaces the confirmed verify tyre(s) at that position, or adds the tyre.
    Odometer photo: its km replaces confirm odometer_km only when confidence >= km_min_confidence."""
    applied = {"tyres_replaced": [], "tyres_added": [], "km": None}
    if not answer:
        return confirm, findings, applied
    findings = list(findings or [])
    for p in answer.get("photos") or []:
        if not isinstance(p, dict):
            continue
        slot, tyre = p.get("slot"), p.get("tyre")
        if slot in TYRE_SLOTS and isinstance(tyre, dict) and (tyre.get("tyre_score") is not None or tyre.get("tread")):
            old = [f for f in findings if f.get("confirmed") and (f.get("tyre") or {}).get("position") == slot]
            findings = [f for f in findings if f not in old]
            findings.append({"item_id": f"photo_{slot}", "confirmed": True, "category": "tyre", "source": "photo",
                             "part": f"{slot}_tyre", "description": p.get("description"),
                             "tyre": {"position": slot, "tyre_score": tyre.get("tyre_score"), "tread": tyre.get("tread")}})
            if old:
                applied["tyres_replaced"].append({"slot": slot, "replaced": [f.get("item_id") for f in old]})
            else:
                applied["tyres_added"].append(slot)
        elif slot == "odometer" and _number(p.get("odometer_km")) and p["odometer_km"] >= 0:
            km, conf = int(p["odometer_km"]), p.get("confidence") if _number(p.get("confidence")) else 0
            used = conf >= km_min_confidence
            applied["km"] = {"photo_km": km, "confidence": conf, "used": used, "confirm_km": confirm.get("odometer_km")}
            if used:
                confirm = {**confirm, "odometer_km": km, "km_source": f"odometer photo ({conf})"}
    return confirm, findings, applied
