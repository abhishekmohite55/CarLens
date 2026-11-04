"""Search helpers: flatten plan queries, dedupe result URLs, totals. Pure: no config, events or run folders."""
from __future__ import annotations


def flatten_queries(q: dict) -> list[dict]:
    """queries.json into one list: listing, new price, then each part, then each tyre marked replace."""
    out = [{"kind": "listing", "for": None, "query": x} for x in q.get("listing") or []]
    out += [{"kind": "new_price", "for": None, "query": x} for x in q.get("new_price") or []]
    out += [{"kind": "part", "for": p.get("part"), "query": x} for p in q.get("parts") or [] for x in p.get("queries") or []]
    out += [{"kind": "tyre", "for": t.get("item_id"), "query": x} for t in q.get("tyres") or [] for x in t.get("queries") or []]
    return out


def dedupe_urls(done: list[dict]) -> list[dict]:
    """Each URL once, with every query that found it (kept for the report links)."""
    urls: dict[str, dict] = {}
    for d in done:
        for r in d.get("results") or []:
            entry = urls.setdefault(r["url"], {"url": r["url"], "title": r.get("title"), "found_by": []})
            entry["found_by"].append(d["query"])
    return list(urls.values())


def search_totals(done: list[dict], urls: list[dict], depth: str, elapsed_s: float) -> dict:
    return {"queries": len(done), "failed": sum(1 for d in done if d.get("error")),
            "results": sum(len(d.get("results") or []) for d in done), "unique_urls": len(urls),
            "credits_estimate": len(done) * (2 if depth == "advanced" else 1), "elapsed_s": elapsed_s}
