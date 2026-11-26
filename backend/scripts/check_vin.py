"""
Run from F:\\CarLens\\backend:
    python -m scripts.check_vin                 # reads scripts/vins.txt
    python -m scripts.check_vin path\\to\\vins.txt

Check-only script (not used by the app). For each VIN it calls:
  1. NHTSA vPIC  DecodeVinValuesExtended   (free, no key)
  2. mcp.vin     /api/vin/{VIN} full report (free, no key, 30 req/min per IP)

Saves raw responses and a side-by-side summary to
    runs/_checks/vin/<timestamp>/
        <VIN>/vpic.json, <VIN>/mcpvin.json   (status, ms, url, body)
        summary.md, summary.csv

vins.txt: one VIN per line. Blank lines and lines starting with # are skipped.
"""
from __future__ import annotations

import csv
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

PROJECT_ROOT = Path(__file__).parent.parent.parent  # F:\CarLens
DEFAULT_VINS = Path(__file__).parent / "vins.txt"
OUT_ROOT = PROJECT_ROOT / "runs" / "_checks" / "vin"

VPIC_URL = "https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVinValuesExtended/{vin}?format=json"
MCPVIN_URL = "https://mcp.vin/api/vin/{vin}"

TIMEOUT_SEC = 30
PAUSE_SEC = 2.5  # keeps mcp.vin under 30 req/min
VIN_RE = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")

# Fields compared side by side: (label, vPIC key, mcp.vin path)
FIELDS = [
    ("year", "ModelYear", "vehicle.year"),
    ("make", "Make", "vehicle.make"),
    ("model", "Model", "vehicle.model"),
    ("trim", "Trim", "vehicle.trim"),
    ("series", "Series", None),
    ("body", "BodyClass", "vehicle.body_class"),
    ("doors", "Doors", "vehicle.doors"),
    ("engine_l", "DisplacementL", "engine.displacement_l"),
    ("cylinders", "EngineCylinders", "engine.cylinders"),
    ("hp", "EngineHP", "engine.hp"),
    ("fuel", "FuelTypePrimary", "engine.fuel_type"),
    ("ev_level", "ElectrificationLevel", "engine.ev_type"),
    ("transmission", "TransmissionStyle", "transmission.type"),
    ("drive", "DriveType", "transmission.drive_type"),
    ("base_price", "BasePrice", None),
    ("plant_country", "PlantCountry", "plant.country"),
    ("vpic_error", "ErrorText", None),
]
# mcp.vin-only extras
EXTRAS = [
    ("checksum_ok", "validation.checksum.valid"),
    ("recalls", "recalls.count"),
    ("open_recalls", "recall_status.open_count"),
    ("complaints", "complaints.count"),
    ("safety_overall", "safety_ratings.overall"),
    ("mpg_combined", "fuel_economy.combined_mpg"),
    ("photo_front", "photos.front"),
    ("decode_source", "decode_source.source"),
]


def _get(d, path: str | None):
    if not path or d is None:
        return None
    cur = d
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _clean(v):
    if v is None:
        return ""
    s = str(v).strip()
    return "" if s.lower() in ("", "none", "null", "not applicable") else s


def _call(url: str) -> dict:
    t0 = time.perf_counter()
    try:
        r = requests.get(url, timeout=TIMEOUT_SEC, headers={"Accept": "application/json"})
        ms = round((time.perf_counter() - t0) * 1000)
        try:
            body = r.json()
        except ValueError:
            body = r.text[:5000]
        return {"url": url, "status": r.status_code, "ms": ms, "body": body}
    except requests.RequestException as e:
        ms = round((time.perf_counter() - t0) * 1000)
        return {"url": url, "status": None, "ms": ms, "error": f"{type(e).__name__}: {e}"}


def _read_vins(path: Path) -> list[str]:
    vins = []
    for line in path.read_text(encoding="utf-8").splitlines():
        v = line.strip().upper()
        if not v or v.startswith("#"):
            continue
        if not VIN_RE.match(v):
            print(f"  warning: {v!r} is not 17 valid VIN characters (still sent)")
        vins.append(v)
    return vins


def _save(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def main() -> int:
    vins_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_VINS
    if not vins_path.exists():
        print(f"VIN file not found: {vins_path}")
        return 1
    vins = _read_vins(vins_path)
    if not vins:
        print("No VINs in file.")
        return 1

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out = OUT_ROOT / ts
    print(f"{len(vins)} VINs -> {out}\n")

    rows = []
    for i, vin in enumerate(vins, 1):
        print(f"[{i}/{len(vins)}] {vin}")
        vp = _call(VPIC_URL.format(vin=vin))
        _save(out / vin / "vpic.json", vp)
        time.sleep(PAUSE_SEC)
        mc = _call(MCPVIN_URL.format(vin=vin))
        _save(out / vin / "mcpvin.json", mc)
        print(f"   vpic {vp.get('status')} {vp['ms']}ms | mcp.vin {mc.get('status')} {mc['ms']}ms")

        vrow = {}
        body = vp.get("body")
        if isinstance(body, dict) and body.get("Results"):
            vrow = body["Results"][0]
        mbody = mc.get("body") if isinstance(mc.get("body"), dict) else None

        row = {"vin": vin, "vpic_status": vp.get("status") or vp.get("error", ""),
               "vpic_ms": vp["ms"], "mcpvin_status": mc.get("status") or mc.get("error", ""),
               "mcpvin_ms": mc["ms"]}
        for label, vkey, mpath in FIELDS:
            row[f"{label}|vpic"] = _clean(vrow.get(vkey))
            row[f"{label}|mcpvin"] = _clean(_get(mbody, mpath)) if mpath else ""
        for label, mpath in EXTRAS:
            row[label] = _clean(_get(mbody, mpath))
        rows.append(row)
        if i < len(vins):
            time.sleep(PAUSE_SEC)

    # CSV: every column
    with open(out / "summary.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    # Markdown: one block per VIN, vPIC vs mcp.vin, mismatches marked
    lines = [f"# VIN check {ts}", "", f"{len(rows)} VINs. Sources: NHTSA vPIC, mcp.vin.", ""]
    for r in rows:
        lines += [f"## {r['vin']}", "",
                  f"vPIC: {r['vpic_status']} ({r['vpic_ms']} ms) | mcp.vin: {r['mcpvin_status']} ({r['mcpvin_ms']} ms)",
                  "", "| field | vPIC | mcp.vin | |", "|---|---|---|---|"]
        for label, _, mpath in FIELDS:
            a, b = r[f"{label}|vpic"], r[f"{label}|mcpvin"]
            flag = "DIFF" if mpath and a and b and a.lower() != b.lower() else ""
            lines.append(f"| {label} | {a} | {b} | {flag} |")
        for label, _ in EXTRAS:
            lines.append(f"| {label} | | {r[label]} | |")
        lines.append("")
    (out / "summary.md").write_text("\n".join(lines), encoding="utf-8")

    ok_v = sum(1 for r in rows if r["vpic_status"] == 200)
    ok_m = sum(1 for r in rows if r["mcpvin_status"] == 200)
    print(f"\nvPIC 200: {ok_v}/{len(rows)} | mcp.vin 200: {ok_m}/{len(rows)}")
    print(f"Summary: {out / 'summary.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
