"""
Dev check (Stage 4): read the number plate from ONE kept frame, calling Gemini exactly the way locate does
(backend/app/llm/gemini_video.py): Files API upload -> wait for ACTIVE -> Part.from_uri ->
GenerateContentConfig with system_instruction, temperature, JSON mime type, response_schema,
media_resolution and thinking_config.

Model, resolution, thinking and temperature come from config.yaml (models.verify, verify_media_resolution,
verify_thinking_level, temperature); nothing is written there.

Saves to runs/_checks/verify_one/<folder>_<item>_plate_<model>_<HHMMSS>/request.json and response.json,
with the time of each step (upload, wait for ACTIVE, Gemini answer).

Run from F:\\CarLens\\backend:
    python -m scripts.check_plate_one probe_20261102_211502_9188_current L1
"""
from __future__ import annotations

import argparse
import json
import threading
import time
from datetime import datetime

from google import genai
from google.genai import types

from app.config import PROJECT_ROOT, get_config

CHECKS_DIR = PROJECT_ROOT / "runs" / "_checks"
POLL_INTERVAL = 2  # seconds between file state checks (locate uses 5; an image is ready much sooner)

SYSTEM_PROMPT = """You read the number plate in one photo of a used car in India.

Return JSON only:
- "readable": true only if you can read the plate characters.
- "plate_text": the registration as printed, capital letters and digits, no spaces, e.g. MH12AB1234. null if not readable.
- "confidence": 0 to 1. 0.9 or more = certain, about 0.6 = likely, below 0.4 = a guess.
- "alternatives": up to 3 other readings when some characters are unclear, otherwise an empty list.
Never invent characters you cannot see."""

RESPONSE_SCHEMA = {
    "type": "object",
    "required": ["readable", "plate_text", "confidence", "alternatives"],
    "properties": {
        "readable": {"type": "boolean"},
        "plate_text": {"type": "string", "nullable": True},
        "confidence": {"type": "number"},
        "alternatives": {"type": "array", "items": {"type": "string"}},
    },
}


def heartbeat(stop: threading.Event, t0: float) -> None:
    """Print elapsed time every 15 s so a long wait is visibly alive."""
    while not stop.wait(15):
        print(f"  ... waiting for Gemini: {time.perf_counter() - t0:.0f} s", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser(description="Read the plate from one kept frame (locate-style call).")
    ap.add_argument("folder", help="frames folder name inside runs/_checks, e.g. probe_20261102_211502_9188_current")
    ap.add_argument("item_id", help="plate item id from manifest.json, e.g. L1 or L8")
    args = ap.parse_args()

    cfg = get_config()
    model = next(m.model for m in cfg.models.verify_chain if m.provider == "google_genai")  # first Gemini entry
    resolution = cfg.models.verify_media_resolution
    thinking = cfg.models.verify_thinking_level
    temperature = cfg.models.temperature

    folder = CHECKS_DIR / args.folder
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    item = next((i for i in manifest["items"] if i["item_id"] == args.item_id and i.get("sharpest")), None)
    if item is None:
        raise SystemExit(f"{args.item_id} not found (or no frame) in {folder}. "
                         f"Items: {', '.join(i['item_id'] + '=' + str(i.get('category')) for i in manifest['items'])}")
    image_path = folder / item["sharpest"]["file"]
    user_prompt = f'Item {item["item_id"]}: {item.get("label")}. Read the number plate and return the JSON.'

    out_dir = CHECKS_DIR / "verify_one" / f"{args.folder}_{args.item_id}_plate_{model}_{datetime.now():%H%M%S}"
    out_dir.mkdir(parents=True)
    request = {
        "model": model, "media_resolution": resolution, "thinking_level": thinking, "temperature": temperature,
        "system_prompt": SYSTEM_PROMPT, "user_prompt": user_prompt, "response_schema": RESPONSE_SCHEMA,
        "image": {"file": str(image_path), "bytes": image_path.stat().st_size},
    }
    (out_dir / "request.json").write_text(json.dumps(request, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"== {image_path.name}  model={model}  resolution={resolution}  thinking={thinking or 'default'}  "
          f"{image_path.stat().st_size // 1024} KB", flush=True)

    timings: dict = {}
    result: dict = {"model": model, "timings_s": timings}
    client = genai.Client()  # keep a reference: a temporary Client is garbage-collected and closes mid-request
    try:
        # 1. Upload (as locate)
        t = time.perf_counter()
        uploaded = client.files.upload(file=image_path)
        timings["upload"] = round(time.perf_counter() - t, 2)
        result["gemini_file_name"] = uploaded.name
        print(f"  uploaded in {timings['upload']} s  ({uploaded.name})", flush=True)

        # 2. Wait for ACTIVE (as locate)
        t = time.perf_counter()
        while True:
            info = client.files.get(name=uploaded.name)
            if info.state == "ACTIVE":
                break
            if info.state == "FAILED":
                raise RuntimeError(f"Gemini file processing failed: {uploaded.name}")
            time.sleep(POLL_INTERVAL)
        timings["wait_active"] = round(time.perf_counter() - t, 2)
        print(f"  file ACTIVE after {timings['wait_active']} s", flush=True)

        # 3. Ask (same config fields as locate)
        cfg_kwargs: dict = dict(
            system_instruction=SYSTEM_PROMPT,
            temperature=temperature,
            response_mime_type="application/json",
            response_schema=RESPONSE_SCHEMA,
            media_resolution=f"MEDIA_RESOLUTION_{resolution.upper()}",
        )
        if thinking:
            cfg_kwargs["thinking_config"] = types.ThinkingConfig(thinking_level=thinking)
        t = time.perf_counter()
        stop = threading.Event()
        threading.Thread(target=heartbeat, args=(stop, t), daemon=True).start()
        try:
            response = client.models.generate_content(
                model=model,
                contents=[
                    types.Part.from_text(text=user_prompt),
                    types.Part.from_uri(file_uri=info.uri, mime_type=info.mime_type or "image/jpeg"),
                ],
                config=types.GenerateContentConfig(**cfg_kwargs),
            )
        finally:
            stop.set()
        timings["ask"] = round(time.perf_counter() - t, 2)
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        (out_dir / "response.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"  FAILED: {result['error']}  timings={timings}")
        return

    usage = response.usage_metadata
    result["tokens"] = {"input": (usage and usage.prompt_token_count) or 0,
                        "output": (usage and usage.candidates_token_count) or 0,
                        "thoughts": (usage and usage.thoughts_token_count) or 0}
    result["raw_text"] = response.text or ""
    try:
        result["parsed"] = json.loads(result["raw_text"])
    except json.JSONDecodeError as exc:
        result["parse_error"] = str(exc)
    (out_dir / "response.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")

    tk = result["tokens"]
    print(f"  answer in {timings['ask']} s  tokens in={tk['input']} out={tk['output']} thoughts={tk['thoughts']}")
    print("  " + (json.dumps(result["parsed"], ensure_ascii=False) if "parsed" in result
                  else f"INVALID JSON: {result['parse_error']}  raw: {result['raw_text'][:300]}"))
    print(f"  -> {out_dir}")


if __name__ == "__main__":
    main()
