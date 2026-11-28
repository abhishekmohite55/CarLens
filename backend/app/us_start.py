"""US run start (stage U2, docs/backend/07-us-market.md §2.2, §6): checks of the upload's VIN / state / miles and the
04_confirm.json written from the VIN car. Pure: no config reads, no database, no events."""
from __future__ import annotations

import re
from typing import Mapping

from .market import US_STATES
from .vin.check import normalise_vin, vin_problem

_MILES = re.compile(r"^(\d{1,3}(,\d{3})+|\d+)$")


class UsFieldError(Exception):
    """A US upload field the user must fix (422). code: vin_invalid / state_invalid / miles_invalid."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


def parse_miles(text: str | None) -> int | None:
    """"48,200" / "48200" → 48200; anything else (decimals, "48k", negative, empty) → None."""
    t = (text or "").strip()
    return int(t.replace(",", "")) if _MILES.match(t) else None


def check_us_fields(vin_text: str | None, state_text: str | None, miles_text: str | None, *,
                    miles_min: int, miles_max: int) -> dict:
    """{vin, state_code, state, miles_user} or UsFieldError. State is optional (empty = US-wide prices)."""
    vin = normalise_vin(vin_text)
    if not vin:
        raise UsFieldError("vin_invalid", "Enter the VIN and look it up first.")
    problem = vin_problem(vin)
    if problem:
        raise UsFieldError("vin_invalid", problem)
    code = (state_text or "").strip().upper() or None
    if code is not None and code not in US_STATES:
        raise UsFieldError("state_invalid", "Pick a US state from the list, or leave it empty for US-wide prices.")
    miles = parse_miles(miles_text)
    if miles is None:
        raise UsFieldError("miles_invalid", "Enter the miles as a whole number, e.g. 48,200.")
    if not miles_min <= miles <= miles_max:
        raise UsFieldError("miles_invalid", f"Miles must be between {miles_min:,} and {miles_max:,}.")
    return {"vin": vin, "state_code": code, "state": US_STATES.get(code) if code else None, "miles_user": miles}


def confirm_from_vin(fields: Mapping, car: Mapping, confirmed_at: str) -> dict:
    """04_confirm.json for a US run: same shape as India's (plan / extract / report read one shape), car from the VIN,
    nothing changed or skipped by the user, no plate / city / km. Extra US keys: vin, state_code, miles_user, source."""
    keep = ("make", "model", "variant", "year", "fuel", "body", "engine", "drive")
    return {
        "car": {k: car.get(k) for k in keep},
        "plate": None, "city": None, "state": fields.get("state"), "odometer_km": None,
        "changed": [], "skipped": [], "photos": [],
        "vin": fields["vin"], "state_code": fields.get("state_code"), "miles_user": fields["miles_user"],
        "source": "vin", "confirmed_at": confirmed_at,
    }
