from app.search import dedupe_urls, flatten_queries, search_totals


def test_flatten_queries_order_and_kinds():
    q = {"listing": ["l1"], "parts": [{"part": "door", "queries": ["p1", "p2"]}],
         "tyres": [{"item_id": "L5", "tier": "replace", "queries": ["t1"]}, {"item_id": "L6", "tier": "ok", "queries": []}]}
    assert flatten_queries(q) == [
        {"kind": "listing", "for": None, "query": "l1"},
        {"kind": "part", "for": "door", "query": "p1"},
        {"kind": "part", "for": "door", "query": "p2"},
        {"kind": "tyre", "for": "L5", "query": "t1"},
    ]


def test_dedupe_urls_and_totals():
    done = [{"query": "a", "error": None, "results": [{"url": "u1", "title": "T1"}, {"url": "u2", "title": "T2"}]},
            {"query": "b", "error": "boom", "results": []},
            {"query": "c", "error": None, "results": [{"url": "u1", "title": "T1"}]}]
    urls = dedupe_urls(done)
    assert urls == [{"url": "u1", "title": "T1", "found_by": ["a", "c"]}, {"url": "u2", "title": "T2", "found_by": ["a"]}]
    t = search_totals(done, urls, "basic", 1.5)
    assert (t["queries"], t["failed"], t["results"], t["unique_urls"], t["credits_estimate"]) == (3, 1, 3, 2, 3)
