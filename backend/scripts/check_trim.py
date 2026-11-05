"""
Dev check (Stage 7c, step 1): trim saved Tavily results into the text the extract LLM would get. No LLM, no Tavily.

Inputs (default: all of them):
    runs/_checks/plan/<case>_<time>/search_<time>/results.json   car from scripts/fake_plan/<case>.json
    runs/<run_id>/07_search/results.json                         car from runs/<run_id>/04_confirm.json
Settings: config.yaml `extract:` (max_results_per_group, max_snippet_chars).

Saves trimmed.txt (exact LLM text), trimmed.json (groups + S-id → URL), stats.json to
    runs/_checks/plan/<case>_<time>/search_<time>/trim_<HHMMSS>/   (check folders)
    runs/_checks/trim/<run_id>_<HHMMSS>/                           (real runs; keeps the run folder clean)

Run from F:\\CarLens\\backend:
    python -m scripts.check_trim
    python -m scripts.check_trim _checks/plan/dent_141738/search_194617  r_20261102_185917_f63f
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from app.config import PROJECT_ROOT, get_config
from app.extract import car_line, render_trimmed, trim_results

RUNS = PROJECT_ROOT / "runs"
FAKE = Path(__file__).parent / "fake_plan"


def _load(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def inputs(names: list[str]) -> list[tuple[str, Path, dict, dict, Path]]:
    """(label, results.json, plan queries, confirm, output folder) per input."""
    stamp = datetime.now().strftime("%H%M%S")
    out = []
    folders = [RUNS / n for n in names] if names else (
        sorted((RUNS / "_checks" / "plan").glob("*/search_*")) + sorted(p.parent for p in RUNS.glob("r_*/07_search")))
    for f in folders:
        if f.name.startswith("search_"):  # check folder
            case = f.parent.name.rsplit("_", 1)[0]
            out.append((f"{f.parent.name}/{f.name}", f / "results.json", _load(f.parent / "queries.json"),
                        _load(FAKE / f"{case}.json")["confirm"], f / f"trim_{stamp}"))
        else:  # real run folder
            out.append((f.name, f / "07_search" / "results.json", _load(f / "06_plan" / "queries.json"),
                        _load(f / "04_confirm.json"), RUNS / "_checks" / "trim" / f"{f.name}_{stamp}"))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("folders", nargs="*", help="paths under runs/: a check search_ folder or a run id (default: all)")
    e = get_config().extract
    for label, results, plan, confirm, out in inputs(ap.parse_args().folders):
        trimmed = trim_results(_load(results), plan, e.max_results_per_group, e.max_snippet_chars)
        text = render_trimmed(car_line(confirm), trimmed)
        trimmed["stats"]["chars_out"] = len(text)
        out.mkdir(parents=True, exist_ok=True)
        (out / "trimmed.txt").write_text(text, encoding="utf-8")
        (out / "trimmed.json").write_text(json.dumps(trimmed, indent=2, ensure_ascii=False), encoding="utf-8")
        (out / "stats.json").write_text(json.dumps(trimmed["stats"], indent=2), encoding="utf-8")
        print(f"\n== {label}\n{trimmed['stats']}")
        print("\n".join(text.splitlines()[:14]), "\n  ...\nsaved", out)


if __name__ == "__main__":
    main()
