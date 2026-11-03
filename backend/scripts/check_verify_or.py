"""
Dev check (Stage 4): full verify request (all kept frames of one folder, prompts/verify.*.md) sent through
LangChain, trying models.verify_chain in config.yaml top to bottom. The next model runs only when the
previous one fails or takes longer than models.verify_timeout_per_model_sec.

Keys in F:\\CarLens\\.env: GEMINI_API_KEY (google_genai), OPENROUTER_API_KEY (openrouter).
Needs: pip install langchain-openrouter   (langchain, langchain-google-genai already in requirements)

Saves to runs/_checks/verify_or/<folder>_<HHMMSS>/:
    request.json   chain, settings, prompts, frames sent (no keys)
    response.json  one attempt per model tried (seconds, tokens, raw text, parsed JSON or error) + problems

Run from F:\\CarLens\\backend:
    python -m scripts.check_verify_or probe_20261102_211502_9188_current          # all items
    python -m scripts.check_verify_or probe_20261102_211502_9188_current L7 L9    # only these items
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage

from app.config import PROJECT_ROOT, get_config  # also loads .env
from app.llm.chat import ask_chain, image_blocks, parse_json

CHECKS_DIR = PROJECT_ROOT / "runs" / "_checks"


def load_frames(folder: Path, item_ids: list[str]) -> list[dict]:
    """Items with a kept frame (all, or only item_ids): item_id, category, label, file."""
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    items = [i for i in manifest["items"] if i.get("sharpest")]
    if item_ids:
        unknown = set(item_ids) - {i["item_id"] for i in items}
        if unknown:
            raise SystemExit(f"not found (or no frame): {', '.join(sorted(unknown))}. "
                             f"Items: {', '.join(i['item_id'] + '=' + str(i.get('category')) for i in items)}")
        items = [i for i in items if i["item_id"] in item_ids]
    return [{"item_id": i["item_id"], "category": i.get("category"), "label": i.get("label"),
             "file": i["sharpest"]["file"]} for i in items]


def check_parsed(parsed: dict, frames: list[dict]) -> list[str]:
    """Problems a human should look at; empty list = the answer covers every item."""
    problems = []
    sent = {f["item_id"] for f in frames}
    got = [x.get("item_id") for x in parsed.get("findings", [])]
    if missing := sorted(sent - set(got)):
        problems.append(f"no finding for: {', '.join(missing)}")
    if extra := sorted(set(map(str, got)) - sent):
        problems.append(f"unknown item ids: {', '.join(extra)}")
    for x in parsed.get("findings", []):
        if not x.get("confirmed") and not x.get("reason"):
            problems.append(f"{x.get('item_id')}: not confirmed but no reason")
    return problems


def print_answer(parsed: dict) -> None:
    for x in parsed.get("findings", []):
        if x.get("confirmed"):
            print(f"  {str(x.get('item_id')):<5} yes  {x.get('part') or '-'} / {x.get('issue') or '-'} / "
                  f"{x.get('severity') or '-'} / {x.get('action') or '-'}")
        else:
            print(f"  {str(x.get('item_id')):<5} NO   {x.get('reason')}")
    vehicle = parsed.get("vehicle") or {}
    print("  plate:", parsed.get("plate"))
    print("  badge:", parsed.get("badge"))
    print("  odometer_km:", parsed.get("odometer_km"))
    print("  vehicle:", " | ".join(f"{k}={(vehicle.get(k) or {}).get('value')} ({(vehicle.get(k) or {}).get('confidence')})"
                                   for k in ("make", "model", "variant", "year", "fuel")))
    print(f"  tyres_assessed={parsed.get('tyres_assessed')}  odometer_found={parsed.get('odometer_found')}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Full verify request through the model chain in config.yaml.")
    ap.add_argument("folder", help="frames folder name inside runs/_checks, e.g. probe_20261102_211502_9188_current")
    ap.add_argument("item_ids", nargs="*", help="only these item ids (default: all items)")
    args = ap.parse_args()

    cfg = get_config()
    chain = cfg.models.verify_chain
    timeout_sec = cfg.models.verify_timeout_per_model_sec
    thinking = cfg.models.verify_thinking_level
    temperature = cfg.models.temperature

    folder = CHECKS_DIR / args.folder
    frames = load_frames(folder, args.item_ids)
    prompts_dir = PROJECT_ROOT / cfg.paths.prompts_dir
    system_prompt = (prompts_dir / "verify.system.md").read_text(encoding="utf-8")
    user_prompt = (prompts_dir / "verify.user.md").read_text(encoding="utf-8").format(frame_count=len(frames))

    out_dir = CHECKS_DIR / "verify_or" / f"{args.folder}_{datetime.now():%H%M%S}"
    out_dir.mkdir(parents=True, exist_ok=True)
    request = {
        "chain": [{"provider": e.provider, "model": e.model} for e in chain],
        "timeout_per_model_sec": timeout_sec, "thinking_level_gemini": thinking, "temperature": temperature,
        "system_prompt": system_prompt, "user_prompt": user_prompt,
        "frames_sent": [{**f, "bytes": (folder / f["file"]).stat().st_size} for f in frames],
    }
    (out_dir / "request.json").write_text(json.dumps(request, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"== {args.folder}  frames={len(frames)}  "
          f"{sum(r['bytes'] for r in request['frames_sent']) // 1024} KB  timeout/model={timeout_sec} s",
          flush=True)

    def build_messages(entry):
        res = cfg.models.verify_media_resolution if entry.provider == "google_genai" else None
        content = image_blocks(user_prompt, frames, folder, res)
        return [SystemMessage(content=system_prompt), HumanMessage(content=content)]

    def validate(parsed: dict) -> str | None:
        problems = check_parsed(parsed, frames)
        return problems[0] if problems else None

    result = ask_chain(
        chain, build_messages,
        temperature=temperature,
        timeout_sec=timeout_sec,
        thinking_level=thinking,
        validate=validate,
        emit=lambda msg: print(f"  {msg}", flush=True),
        callbacks=[],
    )

    if result["answered_by"]:
        winning = next((a for a in result["attempts"] if "error" not in a and "tokens" in a), None)
        if winning:
            tk = winning["tokens"]
            print(f"  answered in {winning['seconds']} s  tokens in={tk['input']} out={tk['output']} "
                  f"reasoning={tk['reasoning']}")
        print_answer(result["parsed"])
        for p in check_parsed(result["parsed"], frames):
            print(f"  PROBLEM: {p}")
    else:
        print("  every model in verify_chain failed")

    (out_dir / "response.json").write_text(
        json.dumps({
            "answered_by": result["answered_by"],
            "attempts": result["attempts"],
            "problems": check_parsed(result["parsed"], frames) if result["parsed"] else [],
        }, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"  -> {out_dir}")


if __name__ == "__main__":
    main()
