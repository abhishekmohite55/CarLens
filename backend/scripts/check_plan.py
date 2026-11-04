"""
Dev check (Stage 7): search planning on fake confirmed cars (scripts/fake_plan/*.json), no video, no Tavily.
Uses the plan node's make_plan(): listing queries from config.yaml plan.listing_templates (Python, no LLM);
the plan LLM (models.plan_chain) only when the case has damage or tyres to judge.

Saves to runs/_checks/plan/<case>_<HHMMSS>/: request.json, response.json (only when the LLM was called), queries.json.

Run from F:\\CarLens\\backend:
    python -m scripts.check_plan              # every case
    python -m scripts.check_plan dent         # one case
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from app.config import PROJECT_ROOT  # also loads .env
from app.nodes.plan import make_plan
from app.plan import car_problem

CASES_DIR = Path(__file__).parent / "fake_plan"
OUT_DIR = PROJECT_ROOT / "runs" / "_checks" / "plan"


def run_case(path: Path) -> None:
    case = json.loads(path.read_text(encoding="utf-8"))
    print(f"\n== {path.stem}: {case.get('note', '')}")
    problem = car_problem(case["confirm"].get("car") or {})
    if problem:
        print("stopped:", problem)
        return
    result = make_plan(case["confirm"], case["findings"], emit=print, callbacks=[])
    out = OUT_DIR / f"{path.stem}_{datetime.now():%H%M%S}"
    out.mkdir(parents=True, exist_ok=True)
    for name in ("request", "response", "queries"):
        if result[name] is not None:
            (out / f"{name}.json").write_text(json.dumps(result[name], indent=2, ensure_ascii=False), encoding="utf-8")

    q = result["queries"]
    if result["response"] and result["response"]["answered_by"]:
        print("answered by", result["response"]["answered_by"]["model"])
    print("listing:", *q["listing"], sep="\n  ")
    print("new price:", *q.get("new_price", []), sep="\n  ")
    for p in q["parts"]:
        print(f"part {p.get('part')} {p.get('finding_ids')}:", *p["queries"], sep="\n  ")
    for t in q["tyres"]:
        print(f"tyre {t.get('item_id')} {t.get('tier')} ({t.get('reason')})", *t["queries"], sep="\n  ")
    print("tyres not seen:", q["tyres_not_seen"] or "none")
    print("problems:", q["problems"] or "none", "\nsaved", out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cases", nargs="*", help="case names in scripts/fake_plan (default: all)")
    names = ap.parse_args().cases
    paths = [CASES_DIR / f"{n}.json" for n in names] if names else sorted(CASES_DIR.glob("*.json"))
    for p in paths:
        run_case(p)


if __name__ == "__main__":
    main()
