"""
Dev check (Stage 7b): run Tavily on plan check output (runs/_checks/plan/<case>_<time>/queries.json).
Uses the search node's search_all() and the helpers in app/search.py. Settings from config.yaml `search:`.
Key: TAVILY_API_KEY in F:\\CarLens\\.env.

Saves next to the queries: runs/_checks/plan/<case>_<time>/search_<HHMMSS>/results.json
    settings, per query (kind, part/tyre, seconds, error, results with title/url/content/score), urls (deduped,
    with every query that found each one), totals.

Run from F:\\CarLens\\backend:
    python -m scripts.check_search                     # latest plan folder of each case
    python -m scripts.check_search dent_141738         # one plan folder
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path

from tavily import TavilyClient

from app.config import PROJECT_ROOT, get_config  # also loads .env
from app.nodes.search import search_all
from app.search import dedupe_urls, flatten_queries, search_totals

PLAN_DIR = PROJECT_ROOT / "runs" / "_checks" / "plan"


def latest_per_case() -> list[Path]:
    best: dict[str, Path] = {}
    for d in sorted(PLAN_DIR.iterdir()):
        if (d / "queries.json").exists():
            best[d.name.rsplit("_", 1)[0]] = d  # sorted, so the last one per case wins
    return list(best.values())


def run_folder(folder: Path, client: TavilyClient) -> None:
    s = get_config().search
    items = flatten_queries(json.loads((folder / "queries.json").read_text(encoding="utf-8")))
    print(f"\n== {folder.name}: {len(items)} queries")
    done, elapsed = search_all(items, client)
    urls = dedupe_urls(done)
    data = {"plan_folder": folder.name, "settings": s.model_dump(), "queries": done, "urls": urls,
            "totals": search_totals(done, urls, s.depth, elapsed)}
    out = folder / f"search_{datetime.now():%H%M%S}"
    out.mkdir()
    (out / "results.json").write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    for d in done:
        print(f"\n[{d['kind']}{' ' + str(d['for']) if d['for'] else ''}] {d['query']}  ({d['seconds']} s)")
        if d["error"]:
            print("  ERROR", d["error"])
        for r in d["results"]:
            snippet = " ".join(str(r.get("content") or "").split())[:200]
            print(f"  - {r.get('title')}\n    {r['url']}\n    {snippet}")
    print("\ntotals:", data["totals"], "\nsaved", out / "results.json")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("folders", nargs="*", help="plan check folders in runs/_checks/plan (default: latest per case)")
    names = ap.parse_args().folders
    key = os.environ.get("TAVILY_API_KEY")
    if not key:
        raise SystemExit("TAVILY_API_KEY not set in .env")
    client = TavilyClient(api_key=key)
    for folder in ([PLAN_DIR / n for n in names] if names else latest_per_case()):
        run_folder(folder, client)


if __name__ == "__main__":
    main()
