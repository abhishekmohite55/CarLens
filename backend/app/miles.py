"""Miles rule (stage U3, docs/backend/07-us-market.md §7). Pure: the caller passes every value.

User miles are always there. Verify's odometer reading counts only at confidence >= min_confidence; a km reading is
converted to miles first. Miles used = the higher of the two; the result says which one won."""
from __future__ import annotations

KM_TO_MILES = 0.621371


def reading_in_miles(value, unit: str | None) -> int | None:
    """The odometer value in whole miles ("km" converted), None when there is no usable number."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    return round(number * KM_TO_MILES) if (unit or "").lower() == "km" else round(number)


def miles_used(user_miles: int, reading_value, reading_unit: str | None, confidence, min_confidence: float) -> dict:
    """{miles_user, reading, unit, confidence, reading_miles, accepted, why, miles_used, source: you | odometer}."""
    reading_miles = reading_in_miles(reading_value, reading_unit)
    try:
        conf = float(confidence) if confidence is not None else None
    except (TypeError, ValueError):
        conf = None
    if reading_miles is None:
        accepted, why = False, "no odometer reading"
    elif conf is None or conf < min_confidence:
        accepted, why = False, f"reading confidence {conf} below {min_confidence}"
    else:
        accepted, why = True, "reading accepted"
    use_reading = accepted and reading_miles > user_miles
    return {"miles_user": user_miles, "reading": reading_value, "unit": reading_unit, "confidence": conf,
            "reading_miles": reading_miles, "accepted": accepted, "why": why,
            "miles_used": reading_miles if use_reading else user_miles, "source": "odometer" if use_reading else "you"}
