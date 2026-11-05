"""
Dev check (Stage 7c, step 2): send trimmed search text to the extract LLM chain (models.extract_chain), then run the
Python checks: price text in snippet, rupees from the text, sanity limits, model + year for listings, outliers.
No Tavily. Input: trim folders written by scripts/check_trim.py.

Saves to <trim folder>/extract_<HHMMSS>/: request.json, response.json (attempts, raw, parsed), figures.json
(kept, rejected with reasons, outliers, per-group summary).

Run from F:\\CarLens\\backend:
    python -m scripts.check_extract                                            # latest trim of every input
    python -m scripts.check_extract _checks/plan/bumper_tyre_142826/search_195821/trim_214629
    # trial: each model alone (no fallback), all at the same time, one extract_<time>_<model>/ folder each
    python -m scripts.check_extract <trim folder> --try openrouter:stealth/crouton-alpha openrouter:recursive/flint-v1.0:free
"""
from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from app.config import PROJECT_ROOT, ModelEntry, get_config  # also loads .env
from app.nodes.extract import make_extract

RUNS = PROJECT_ROOT / "runs"
FAKE = Path(__file__).parent / "fake_plan"


def _load(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def car_for(trim: Path) -> dict:
    if trim.parent.name.startswith("search_"):  # runs/_checks/plan/<case>_<time>/search_<time>/trim_<time>
        return _load(FAKE / f"{trim.parent.parent.name.rsplit('_', 1)[0]}.json")["confirm"]["car"]
    return _load(RUNS / trim.name.rsplit("_", 1)[0] / "04_confirm.json")["car"]  # runs/_checks/trim/<run_id>_<time>


def latest_trims() -> list[Path]:
    found = sorted(RUNS.glob("_checks/plan/*/search_*/trim_*")) + sorted(RUNS.glob("_checks/trim/*"))
    best: dict[str, Path] = {}
    for t in found:
        key = str(t.parent) if t.name.startswith("trim_") else t.name.rsplit("_", 1)[0]
        best[key] = t  # sorted, so the newest per input wins
    return list(best.values())


def run_trim(trim: Path, entries: list[ModelEntry] | None = None, tag: str = "", quiet: bool = False) -> dict:
    """Extract one trim folder through `entries` (default models.extract_chain). Returns a one-line summary."""
    entries = entries or get_config().models.extract_chain
    say = (lambda *a, **k: None) if quiet else print
    trimmed, text, car = _load(trim / "trimmed.json"), (trim / "trimmed.txt").read_text(encoding="utf-8"), car_for(trim)
    out = trim / f"extract_{datetime.now():%H%M%S}{tag}"
    out.mkdir()
    say(f"\n== {trim.relative_to(RUNS)} ({len(text)} chars trimmed)")
    result = make_extract(trimmed, text, car, emit=say, callbacks=[], entries=entries)
    for name in ("request", "response", "figures"):
        if result[name] is not None:
            (out / f"{name}.json").write_text(json.dumps(result[name], indent=2, ensure_ascii=False), encoding="utf-8")
    answer, figs = result["response"], result["figures"]
    last = answer["attempts"][-1] if answer["attempts"] else {}
    row = {"model": entries[-1].model, "seconds": last.get("seconds"), "tokens": last.get("tokens"),
           "error": last.get("error"), "figures": None, "kept": None, "rejected": None, "folder": out}
    if figs is None:
        say("every extract model failed; saved", out)
        return row

    kept, rejected, outliers, summary = figs["kept"], figs["rejected"], figs["outliers"], figs["summary"]
    row.update(figures=len(answer["parsed"]["figures"]), kept=len(kept), rejected=len(rejected) + len(outliers))
    say("answered by", answer["answered_by"]["model"],
          f"| figures {len(answer['parsed']['figures'])}: kept {len(kept)}, rejected {len(rejected)}, outliers {len(outliers)}")
    for g, s in summary.items():
        say(f"  {g}: {s['figures']} figures, ₹{s['min_inr']:,} – ₹{s['max_inr']:,}")
    for r in rejected + outliers:
        say(f"  dropped {r.get('source')} {r.get('price_text')}: {r['reason']}")
    say("saved", out)
    return row


def try_models(trim: Path, specs: list[str]) -> None:
    """Each provider:model alone, in parallel, then a comparison table."""
    entries = [ModelEntry(provider=s.split(":", 1)[0], model=s.split(":", 1)[1]) for s in specs]
    print(f"trying {len(entries)} models on {trim.relative_to(RUNS)} (in parallel, quiet until done)")
    with ThreadPoolExecutor(max_workers=len(entries)) as pool:
        rows = list(pool.map(lambda e: run_trim(trim, [e], "_" + e.model.replace("/", "-").replace(":", "-"), True), entries))
    print(f"\n{'model':<38}{'seconds':>8}  {'tokens in/out (reasoning)':<26}{'figures':>8}{'kept':>6}{'dropped':>8}")
    for r in rows:
        t = r["tokens"] or {}
        tok = f"{t.get('input')}/{t.get('output')} ({t.get('reasoning')})" if t else "-"
        print(f"{r['model']:<38}{r['seconds'] or '-':>8}  {tok:<26}{r['figures'] or '-':>8}{r['kept'] or '-':>6}{r['rejected'] or '-':>8}")
        if r["error"]:
            print(f"    error: {r['error'][:150]}")
        print(f"    {r['folder'].relative_to(RUNS)}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("trims", nargs="*", help="trim folders under runs/ (default: newest trim of every input)")
    ap.add_argument("--try", dest="try_models", nargs="+", metavar="PROVIDER:MODEL",
                    help="compare these models, each alone and in parallel (needs one trim folder)")
    args = ap.parse_args()
    names = args.trims
    if args.try_models:
        if len(names) != 1:
            raise SystemExit("--try needs exactly one trim folder")
        try_models(RUNS / names[0], args.try_models)
        return
    for t in ([RUNS / n for n in names] if names else latest_trims()):
        run_trim(t)


if __name__ == "__main__":
    main()
