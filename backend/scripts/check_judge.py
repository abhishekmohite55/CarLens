"""
Dev check (owner 28 Nov 2026): can the LLM label search prices well enough for code to pair them later?
- new_price: year, make, model, trim, drivetrain, type, match (exact / same_model_other_trim / ...)
- listing:   the same plus miles; type single_listing / trade_in / private_party / dealer_retail / ...
- parts:     part, position, work (buffing / repaint / new_part / labour / ...), new_or_repair, car_specific, match
Every label comes with the LLM's confidence (0-1). No keep / reject and no depreciation math here: labels only.

Input: the groups of a run's saved extract input (08_extract/trimmed.json, same S ids as the run). One call per group
to the extract model chain with this script's own prompts (scripts/check_judge_<group>.md, not the live prompts).
Each table also shows "price text in snippet" and what the run's extract did. No Tavily; the run and database do
not change. Config and models: the version pinned on the run. Tyres are not checked.

Saves to runs/<run_id>/_checks/judge_<HHMMSS>[_<model>]/: <group>_request.json, <group>_response.json,
<group>_labels.json.

Run from F:\\CarLens\\backend (.venv active, Postgres running):
    python -m scripts.check_judge r_hdh1u76sly7t                          # all three groups
    python -m scripts.check_judge r_hdh1u76sly7t --group listing parts
    python -m scripts.check_judge r_hdh1u76sly7t --try openrouter:<model> google_genai:<model>
    # no LLM call: the program's checks (scripts/judge_rules.py) on a saved judge folder → program_check.json
    python -m scripts.check_judge r_hdh1u76sly7t --offline judge_134037
    # stage E1: the app's own labelled extract (one LLM call, app/extract_rules.py), any market, on a saved run
    # → runs/<run_id>/_checks/app_extract_<HHMMSS>/. Use it on an India run before switching India to labels.
    python -m scripts.check_judge <run_id> --app
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from langchain_core.messages import HumanMessage

from app.config import PROJECT_ROOT, ModelEntry, get_config, pinned_run  # also loads .env
from app.extract import _squash, parse_usd, render_trimmed
from app.llm.chat import ask_chain
from app.results import load_result
from app.vin.match import car_line
from app.extract import car_line as confirm_line
from app.nodes.extract import make_extract
from scripts.judge_rules import program_check

RUNS = PROJECT_ROOT / "runs"
HERE = Path(__file__).parent

# group → (does a trimmed group belong to it, label columns shown in the table, column width)
GROUPS = {
    "new_price": (lambda g: g["key"] == "new_price",
                  [("year", 6), ("model", 8), ("trim", 22), ("drivetrain", 10), ("type", 18), ("match", 30)]),
    "listing": (lambda g: g["key"] == "listing",
                [("year", 6), ("model", 8), ("trim", 22), ("drivetrain", 10), ("miles", 13), ("type", 22),
                 ("match", 30)]),
    "parts": (lambda g: str(g.get("label") or "").startswith("part"),
              [("part", 22), ("position", 16), ("work", 24), ("new_or_repair", 18), ("car_specific", 18),
               ("match", 22)]),
}


def _dump(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def the_car(confirm: dict) -> str:
    car = confirm.get("car") or {}
    return car_line(car) + (f", drive: {car['drive']}" if car.get("drive") else ", drive: not known")


def subset(trimmed: dict, belongs) -> dict:
    groups = [g for g in trimmed["groups"] if belongs(g)]
    keys = {g["key"] for g in groups}
    return {"groups": groups, "sources": {k: v for k, v in trimmed["sources"].items() if v["group"] in keys}}


def run_verdicts(figures: dict | None) -> dict[tuple[str, int | None], str]:
    """(source, first amount) → what the run's extract did: kept / rejected: reason / outlier."""
    out: dict[tuple[str, int | None], str] = {}
    for status, rows in (("kept", (figures or {}).get("kept")), ("rejected", (figures or {}).get("rejected")),
                         ("outlier", (figures or {}).get("outliers"))):
        for f in rows or []:
            texts = f.get("price_text") or []
            texts = [texts] if isinstance(texts, str) else texts
            key = (f.get("source"), parse_usd(texts[0]) if texts else None)
            out[key] = status + (f": {f['reason']}" if status == "rejected" and f.get("reason") else "")
    return out


def _cell(f: dict, field: str) -> str:
    """'Touring (.90)': the label with the LLM's confidence for it."""
    value = f.get(field)
    if value is None:
        return "-"
    conf = (f.get("confidence") or {}).get(field) if isinstance(f.get("confidence"), dict) else None
    return f"{value} ({conf:.2f})" if isinstance(conf, (int, float)) else str(value)


def check_group(name: str, run_id: str, trimmed: dict, car: str, before: dict, entries, out: Path) -> None:
    belongs, columns = GROUPS[name]
    part = subset(trimmed, belongs)
    items = {it["id"]: it for g in part["groups"] for it in g["items"]}
    print(f"\n== {name}: {len(items)} results in {len(part['groups'])} group(s)")
    if not items:
        return
    cfg = get_config()
    snippets = render_trimmed(car, part).split("\n", 2)[2]  # without the CAR line
    prompt = (HERE / f"check_judge_{name}.md").read_text(encoding="utf-8").replace("{car}", car).replace(
        "{snippets}", snippets)
    _dump(out / f"{name}_request.json", {"chain": [{"provider": m.provider, "model": m.model} for m in entries],
                                         "prompt": prompt})
    answer = ask_chain(
        entries, lambda entry: [HumanMessage(content=prompt)],
        temperature=cfg.models.temperature, timeout_sec=cfg.models.extract_timeout_per_model_sec, thinking_level=None,
        validate=lambda p: None if isinstance(p, dict) and isinstance(p.get("figures"), list) else "no figures list",
        emit=print, callbacks=[], reasoning_effort=cfg.models.extract_reasoning_effort,
        max_in_flight=cfg.models.max_calls_in_flight)
    _dump(out / f"{name}_response.json", answer)
    if answer["parsed"] is None:
        print("every model failed")
        return

    rows = []
    for f in answer["parsed"]["figures"]:
        if not isinstance(f, dict):
            continue
        texts = f.get("price_text") or []
        texts = [texts] if isinstance(texts, str) else texts
        sid = f.get("source")
        in_snippet = sid in items and bool(texts) and all(_squash(t) in _squash(items[sid]["snippet"]) for t in texts)
        amount = parse_usd(texts[0]) if texts else None
        rows.append({**f, "price_text": texts, "group_label": next((g["label"] for g in part["groups"]
                                                                  if any(i["id"] == sid for i in g["items"])), None),
                     "in_snippet": in_snippet, "amount": amount,
                     "run_extract": before.get((sid, amount), "not in run's figures")})
    _dump(out / f"{name}_labels.json", {"answered_by": answer["answered_by"], "car": car, "rows": rows})

    matches: dict[str, int] = {}
    for r in rows:
        matches[str(r.get("match"))] = matches.get(str(r.get("match")), 0) + 1
    print(f"answered by {answer['answered_by']['model']}: {len(rows)} prices | "
          + ", ".join(f"{k} {v}" for k, v in sorted(matches.items())))
    print(f"{'src':<5}{'price':<20}" + "".join(f"{c:<{w}}" for c, w in columns) + f"{'run extract':<30}reason")
    label = None
    num = lambda sid: int(sid[1:]) if str(sid).startswith("S") and str(sid)[1:].isdigit() else 0
    for r in sorted(rows, key=lambda r: (str(r.get("group_label")), num(r.get("source")))):
        if name == "parts" and r["group_label"] != label:
            label = r["group_label"]
            print(f"  [{label}]")
        flag = "" if r["in_snippet"] else "  [price text not in snippet]"
        print(f"{str(r.get('source')):<5}{' – '.join(r['price_text'])[:19]:<20}"
              + "".join(f"{_cell(r, c)[:w - 1]:<{w}}" for c, w in columns)
              + f"{r['run_extract'][:29]:<30}{r.get('reason') or ''}{flag}")


def check(run_id: str, groups: list[str], entries: list[ModelEntry] | None, tag: str = "") -> None:
    with pinned_run(run_id):  # the run's config version and models
        entries = entries or get_config().models.extract_chain
        trimmed = load_result(run_id, "08_extract/trimmed.json")
        confirm = load_result(run_id, "04_confirm.json")
        if trimmed is None or confirm is None:
            raise SystemExit(f"{run_id}: no saved extract input or confirm (run extract first; is Postgres up?)")
        car = the_car(confirm)
        before = run_verdicts(load_result(run_id, "08_extract/figures.json"))
        out = RUNS / run_id / "_checks" / f"judge_{datetime.now():%H%M%S}{tag}"
        out.mkdir(parents=True)
        print(f"{run_id}: {car}")
        for name in groups:
            check_group(name, run_id, trimmed, car, before, entries, out)
        print("\nsaved", out)


def offline(run_id: str, folder: str, groups: list[str]) -> None:
    """The program's checks on saved labels; no LLM call."""
    out = RUNS / run_id / "_checks" / folder
    result: dict[str, list] = {}
    for name in groups:
        path = out / f"{name}_labels.json"
        if not path.exists():
            continue
        rows = json.loads(path.read_text(encoding="utf-8"))["rows"]
        checked = [{"source": r.get("source"), "price_text": r.get("price_text"), "match": r.get("match"),
                    "program_check": program_check(r, name)} for r in rows]
        result[name] = checked
        passed = sum(c["program_check"] == "pass" for c in checked)
        print(f"\n== {name}: {passed} pass, {len(checked) - passed} rejected")
        for c in checked:
            print(f"{str(c['source']):<5}{' – '.join(c['price_text'] or [])[:19]:<20}{str(c['match'])[:27]:<28}"
                  f"{c['program_check']}")
    _dump(out / "program_check.json", result)
    print("\nsaved", out / "program_check.json")


def app_extract(run_id: str, entries: list[ModelEntry] | None, tag: str = "") -> None:
    """The app's labelled extract on a run's saved trimmed search results (stage E1). Nothing in the run changes."""
    with pinned_run(run_id):
        trimmed = load_result(run_id, "08_extract/trimmed.json")
        confirm = load_result(run_id, "04_confirm.json")
        if trimmed is None or confirm is None:
            raise SystemExit(f"{run_id}: no saved extract input or confirm (run extract first; is Postgres up?)")
        out = RUNS / run_id / "_checks" / f"app_extract_{datetime.now():%H%M%S}{tag}"
        out.mkdir(parents=True)
        text = render_trimmed(confirm_line(confirm), trimmed)
        result = make_extract(trimmed, text, confirm.get("car") or {}, emit=print, callbacks=[], entries=entries,
                              plan_queries=load_result(run_id, "06_plan/queries.json"), mode="labels")
        for name in ("request", "response", "figures"):
            if result[name] is not None:
                _dump(out / f"{name}.json", result[name])
        figs = result["figures"]
        if figs is None:
            print("every model failed; saved", out)
            return
        print(f"answered by {figs['answered_by']['model']}: kept {len(figs['kept'])}, rejected {len(figs['rejected'])}")
        print(f"{'':<9}{'src':<5}{'group':<16}{'price':<22}{'match':<24}{'trim / work':<24}reason")
        for status, rows in (("kept", figs["kept"]), ("rejected", figs["rejected"])):
            for r in rows:
                price = " – ".join(r.get("price_text") or [])
                what = r.get("trim") or r.get("work") or r.get("type") or "-"
                print(f"{status:<9}{str(r.get('source')):<5}{str(r.get('group'))[:15]:<16}{price[:21]:<22}"
                      f"{str(r.get('match') or r.get('about') or '-')[:23]:<24}{str(what)[:23]:<24}"
                      f"{r.get('reason') if status == 'rejected' else r.get('llm_reason') or ''}")
        print("\nsaved", out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("run_id")
    ap.add_argument("--group", nargs="+", choices=list(GROUPS), default=list(GROUPS))
    ap.add_argument("--try", dest="try_models", nargs="+", metavar="PROVIDER:MODEL",
                    help="run once per model, each alone (one folder each)")
    ap.add_argument("--app", action="store_true", help="the app's labelled extract (stage E1), one LLM call")
    ap.add_argument("--offline", metavar="JUDGE_FOLDER", help="no LLM: program checks on runs/<run>/_checks/<folder>")
    args = ap.parse_args()
    if args.offline:
        offline(args.run_id, args.offline, args.group)
        return
    if args.app:
        specs = args.try_models or [None]
        for spec in specs:
            e = ModelEntry(provider=spec.split(":", 1)[0], model=spec.split(":", 1)[1]) if spec else None
            app_extract(args.run_id, [e] if e else None, "_" + e.model.replace("/", "-").replace(":", "-") if e else "")
        return
    if not args.try_models:
        check(args.run_id, args.group, None)
        return
    for s in args.try_models:
        e = ModelEntry(provider=s.split(":", 1)[0], model=s.split(":", 1)[1])
        check(args.run_id, args.group, [e], "_" + e.model.replace("/", "-").replace(":", "-"))


if __name__ == "__main__":
    main()
