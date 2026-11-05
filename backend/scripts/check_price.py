"""
Dev check (Stage 7d): Python-only pricing on extract check output (figures.json). No LLM, no Tavily, re-run freely.
Rules in app/pricing.py, settings from config.yaml `pricing:`.

Saves price.json next to figures.json (every step: new price, listings used with yearly rate, fair value, repairs,
after repairs as median → max) and prints a short summary.

Run from F:\\CarLens\\backend:
    python -m scripts.check_price                     # newest extract of every input
    python -m scripts.check_price _checks/plan/bumper_tyre_142826/search_195821/trim_214629/extract_221358
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from app.config import PROJECT_ROOT, get_config
from app.pricing import price_report

RUNS = PROJECT_ROOT / "runs"


def _load(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def plan_queries_for(extract: Path) -> dict:
    trim = extract.parent
    if trim.parent.name.startswith("search_"):          # plan/<case>/search_<t>/trim_<t>/extract_<t>
        return _load(trim.parent.parent / "queries.json")
    return _load(RUNS / trim.name.rsplit("_", 1)[0] / "06_plan" / "queries.json")   # _checks/trim/<run>_<t>/extract_<t>


def latest_extracts() -> list[Path]:
    best: dict[str, Path] = {}
    for f in sorted(RUNS.glob("_checks/**/extract_*/figures.json")):
        trim = f.parent.parent
        key = str(trim.parent) if trim.name.startswith("trim_") else trim.name.rsplit("_", 1)[0]
        best[key] = f.parent  # newest extract per search input (check folder or run id)
    return list(best.values())


def run(extract: Path) -> None:
    p = get_config().pricing
    figs = _load(extract / "figures.json")
    settings = {"min_listings_with_year": p.min_listings_with_year, "max_from_top": p.max_from_top, "min_listing_age": p.min_listing_age,
                "tyre_minor_wear_deduction_inr": p.tyre_minor_wear_deduction_inr}
    out = price_report(figs["kept"], plan_queries_for(extract).get("tyres") or [], figs["car"],
                       datetime.now().year, settings)
    (extract / "price.json").write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")

    car = figs["car"]
    print(f"\n== {extract.relative_to(RUNS)}\n{car.get('make')} {car.get('model')} {car.get('variant') or ''} {car.get('year')}")
    np = out["new_price"]
    print("new price:", f"₹{np['value']:,.0f} ({np['type']}, variant match: {np['variant_match']}, from {np['sources']})" if np else "none")
    for x in out.get("listings_used", []):
        print(f"  listing {x['source']} {x['year']} ₹{x['price']:,.0f} → keeps {x['rate']:.3f}/year")
    for x in out.get("listings_dropped", []):
        print(f"  dropped {x['source']} {x['year']} ₹{x['price']:,.0f}: {x['reason']}")
    for i in out["repairs"]["items"]:
        print(f"  repair {i['for']}: ₹{i['cost']:,.0f} ({i['note'] if 'note' in i else i['fixed']})")
    if out["status"] != "ok":
        print("VALUATION UNAVAILABLE:", out["reason"])
    else:
        k, f, a = out["yearly_value_kept"], out["fair_value"], out["after_repairs"]
        print(f"yearly value kept: median {k['median']:.3f}, max {k['max']:.3f} (average of top {p.max_from_top}); age {out['car_age_years']} years")
        print(f"fair value ₹{f['median']:,} – ₹{f['max']:,}; repairs ₹{out['repairs']['total']:,.0f}")
        print(f"PRICE (after repairs) ₹{a['median']:,} – ₹{a['max']:,}")
    print("saved", extract / "price.json")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("extracts", nargs="*", help="extract folders under runs/ (default: newest per input)")
    names = ap.parse_args().extracts
    for e in ([RUNS / n for n in names] if names else latest_extracts()):
        run(e)


if __name__ == "__main__":
    main()
