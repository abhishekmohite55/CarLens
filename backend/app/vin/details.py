"""Vehicle details (stage U4, docs/backend/07-us-market.md §6 vin_details): a details provider's answer → one small
shape for plan and the report. Pure. The field map comes from config (vin.providers.<name>.fields, dotted paths)."""
from __future__ import annotations

from typing import Any, Mapping

from .mapping import _get, pick


def _number(value: Any) -> float | int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return value
    try:
        f = float(str(value).replace(",", ""))
    except ValueError:
        return None
    return int(f) if f.is_integer() else f


def details_from(raw: Mapping, fields: Mapping[str, str], recalls_path: str, top_recalls: int) -> dict:
    """{recalls, open_recalls, complaints, safety_overall, safety_frontal_driver, mpg_city, mpg_highway, mpg_combined,
    annual_fuel_cost, recall_list: [{campaign, component, summary}], ok}. Numbers stay numbers; missing = None."""
    picked = pick(raw, fields)
    out: dict[str, Any] = {name: _number(value) for name, value in picked.items()}
    items = _get(raw, recalls_path) or []
    out["recall_list"] = [{"campaign": r.get("campaign_number"), "component": r.get("component"),
                           "summary": " ".join(str(r.get("summary") or "").split())[:300]}
                          for r in items[:max(top_recalls, 0)] if isinstance(r, Mapping)]
    out["ok"] = any(v is not None for k, v in out.items() if k not in ("recall_list", "ok"))
    return out


def details_lines(d: Mapping | None) -> list[str]:
    """Short lines for the report and the plan prompt; [] when there are no details."""
    if not d or not d.get("ok"):
        return []
    lines = []
    if d.get("recalls") is not None:
        open_part = f", {d['open_recalls']} open for this VIN" if d.get("open_recalls") is not None else ""
        lines.append(f"Recalls (model and year): {d['recalls']}{open_part}")
    if d.get("complaints") is not None:
        lines.append(f"NHTSA complaints (model and year): {d['complaints']}")
    stars = [f"{name} {d[key]}★" for name, key in (("overall", "safety_overall"), ("frontal driver", "safety_frontal_driver"))
             if d.get(key) is not None]
    if stars:
        lines.append("NHTSA safety: " + ", ".join(stars))
    if d.get("mpg_combined") is not None:
        lines.append(f"EPA fuel economy: {d['mpg_combined']} mpg combined"
                     + (f" ({d['mpg_city']} city / {d['mpg_highway']} highway)" if d.get("mpg_city") else ""))
    return lines
