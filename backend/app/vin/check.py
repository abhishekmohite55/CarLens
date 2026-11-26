"""VIN format check (pure): 17 characters, letters and digits without I, O, Q, check digit at position 9."""
from __future__ import annotations

import re

VIN_LENGTH = 17
_ALLOWED = re.compile(r"^[A-HJ-NPR-Z0-9]+$")
# ISO 3779 / 49 CFR 565: letter values and position weights for the check digit
_VALUES = {**{str(d): d for d in range(10)},
           "A": 1, "B": 2, "C": 3, "D": 4, "E": 5, "F": 6, "G": 7, "H": 8,
           "J": 1, "K": 2, "L": 3, "M": 4, "N": 5, "P": 7, "R": 9,
           "S": 2, "T": 3, "U": 4, "V": 5, "W": 6, "X": 7, "Y": 8, "Z": 9}
_WEIGHTS = (8, 7, 6, 5, 4, 3, 2, 10, 0, 9, 8, 7, 6, 5, 4, 3, 2)


def normalise_vin(text: str | None) -> str:
    """Upper case, spaces and dashes removed (people paste "1hgcm 8264 3a104332")."""
    return re.sub(r"[\s-]", "", text or "").upper()


def check_digit(vin: str) -> str:
    """The check digit a 17-character VIN of allowed characters must have at position 9 ("0"–"9" or "X")."""
    total = sum(_VALUES[c] * w for c, w in zip(vin, _WEIGHTS))
    rest = total % 11
    return "X" if rest == 10 else str(rest)


def vin_problem(vin: str) -> str | None:
    """A plain message saying what is wrong with a normalised VIN, or None when it is a valid VIN."""
    if len(vin) != VIN_LENGTH:
        return f"A VIN has {VIN_LENGTH} characters (you typed {len(vin)})."
    if any(c in "IOQ" for c in vin):
        return "A VIN never contains the letters I, O or Q."
    if not _ALLOWED.match(vin):
        return "A VIN has only letters and numbers."
    if vin[8] != check_digit(vin):
        return "This VIN does not add up (check digit). Check it for typos."
    return None


def is_valid_vin(vin: str) -> bool:
    return vin_problem(vin) is None
