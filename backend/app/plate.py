from __future__ import annotations

import re
from collections import defaultdict

_PLATE_RE = re.compile(r'^[A-Z]{2}\d{1,2}[A-Z]{1,3}\d{4}$')
_BH_RE = re.compile(r'^\d{2}BH\d{4}[A-Z]{1,2}$')


def normalise_plate(text: str) -> str:
    return re.sub(r'[\s\-.]', '', text).upper()


def is_indian_plate(text: str) -> bool:
    return bool(_PLATE_RE.match(text) or _BH_RE.match(text))


def plates_in_texts(texts: list[str]) -> list[str]:
    seen: set[str] = set()
    result = []
    for t in texts:
        n = normalise_plate(t)
        if is_indian_plate(n) and n not in seen:
            seen.add(n)
            result.append(n)
    return result


def pick_plate(readings: list[tuple[str, float]], frames_tried: int) -> dict | None:
    if not readings:
        return None
    groups: dict[str, list[float]] = defaultdict(list)
    for plate, score in readings:
        groups[plate].append(score)
    # most frequent; tie → highest mean score
    winner = max(groups, key=lambda p: (len(groups[p]), sum(groups[p]) / len(groups[p])))
    win_scores = groups[winner]
    frames_agree = len(win_scores)
    mean_score = sum(win_scores) / frames_agree
    confidence = round(frames_agree / frames_tried * mean_score, 2)
    alternatives = [p for p in groups if p != winner][:3]
    return {
        "text": winner,
        "confidence": confidence,
        "alternatives": alternatives,
        "frames_agree": frames_agree,
        "frames_tried": frames_tried,
    }
