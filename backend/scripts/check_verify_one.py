"""
Dev check (Stage 4): send ONE kept frame to Gemini with a short damage-only prompt.
Google's own SDK (google-genai) only. Model, resolution, thinking and temperature come from
config.yaml (models.verify, verify_media_resolution, verify_thinking_level, temperature); nothing is written there.

Saves to runs/_checks/verify_one/<folder>_<item>_<model>_<HHMMSS>/:
    request.json   model, settings, prompts, image sent (no keys)
    response.json  raw text, parsed JSON, tokens, time (or the error)
    boxed.jpg      the image with the returned box drawn

Run from F:\\CarLens\\backend:
    python -m scripts.check_verify_one probe_20261102_211502_9188_current L9
"""
from __future__ import annotations

import argparse
import json
import threading
import time
from datetime import datetime
from pathlib import Path

import cv2
from google import genai
from google.genai import types

from app.config import PROJECT_ROOT, get_config

CHECKS_DIR = PROJECT_ROOT / "runs" / "_checks"

SYSTEM_PROMPT = """You check one photo of a used car for damage.
An earlier step thinks this photo shows the damage described in the message.

Return JSON only, with these keys:
- "confirmed": true only if real damage is visible. Reflections, dirt, water marks, shadows and glare are not damage.
- "part": the car part in snake_case, e.g. left_rear_door. null if not confirmed.
- "issue": dent, scratch, crack, broken, missing, paint, rust or other. null if not confirmed.
- "severity": cosmetic, minor, moderate or severe. null if not confirmed.
- "action": none, repair or replace.
- "description": one plain sentence, at most 25 words.
- "box_2d": [ymin, xmin, ymax, xmax] scaled 0 to 1000, tight around the damage. null if not confirmed.
- "reason": only when confirmed is false, one short sentence.
Never invent. If you are not sure, say so in the description."""


def find_item(folder: Path, item_id: str) -> dict:
    """The manifest entry for item_id (must have a kept frame)."""
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    for item in manifest["items"]:
        if item["item_id"] == item_id and item.get("sharpest"):
            return item
    ids = [i["item_id"] for i in manifest["items"]]
    raise SystemExit(f"{item_id} not found (or no frame) in {folder}. Items: {', '.join(ids)}")


def box_to_pixels(box_2d: list[int], width: int, height: int) -> tuple[int, int, int, int]:
    """Gemini [ymin, xmin, ymax, xmax] on 0-1000 -> (x1, y1, x2, y2) pixels."""
    ymin, xmin, ymax, xmax = box_2d
    return (round(xmin * width / 1000), round(ymin * height / 1000),
            round(xmax * width / 1000), round(ymax * height / 1000))


def heartbeat(stop: threading.Event, t0: float) -> None:
    """Print elapsed time every 15 s so a long wait is visibly alive."""
    while not stop.wait(15):
        print(f"  ... waiting: {time.perf_counter() - t0:.0f} s", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser(description="Send one kept frame to Gemini (damage check).")
    ap.add_argument("folder", help="frames folder name inside runs/_checks, e.g. probe_20261102_211502_9188_current")
    ap.add_argument("item_id", help="item id from manifest.json, e.g. L9")
    args = ap.parse_args()

    cfg = get_config()
    model = next(m.model for m in cfg.models.verify_chain if m.provider == "google_genai")  # first Gemini entry
    resolution = cfg.models.verify_media_resolution
    thinking = cfg.models.verify_thinking_level
    temperature = cfg.models.temperature

    folder = CHECKS_DIR / args.folder
    item = find_item(folder, args.item_id)
    image_path = folder / item["sharpest"]["file"]
    image_bytes = image_path.read_bytes()
    user_prompt = (f'Item {item["item_id"]}: {item.get("category")}, "{item.get("label")}". '
                   f"Check this photo and return the JSON.")

    out_dir = CHECKS_DIR / "verify_one" / f"{args.folder}_{args.item_id}_{model}_{datetime.now():%H%M%S}"
    out_dir.mkdir(parents=True)
    request = {
        "model": model, "media_resolution": resolution, "thinking_level": thinking, "temperature": temperature,
        "system_prompt": SYSTEM_PROMPT, "user_prompt": user_prompt,
        "image": {"file": str(image_path), "bytes": len(image_bytes)},
    }
    (out_dir / "request.json").write_text(json.dumps(request, indent=2, ensure_ascii=False), encoding="utf-8")

    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        temperature=temperature,
        response_mime_type="application/json",
        thinking_config=types.ThinkingConfig(thinking_level=thinking) if thinking else None,
    )
    contents = [
        types.Part.from_text(text=user_prompt),
        types.Part(inline_data=types.Blob(data=image_bytes, mime_type="image/jpeg"),
                   media_resolution=types.PartMediaResolution(level=f"MEDIA_RESOLUTION_{resolution.upper()}")),
    ]

    print(f"== {image_path.name}  model={model}  resolution={resolution}  thinking={thinking or 'default'}  "
          f"{len(image_bytes) // 1024} KB", flush=True)
    client = genai.Client()  # keep a reference: a temporary Client is garbage-collected and closes mid-request
    t0 = time.perf_counter()
    stop = threading.Event()
    threading.Thread(target=heartbeat, args=(stop, t0), daemon=True).start()
    try:
        response = client.models.generate_content(model=model, contents=contents, config=config)
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        (out_dir / "response.json").write_text(json.dumps({"error": error}, indent=2), encoding="utf-8")
        print(f"  FAILED after {time.perf_counter() - t0:.1f} s: {error}")
        return
    finally:
        stop.set()
    duration_s = round(time.perf_counter() - t0, 2)

    usage = response.usage_metadata
    tokens = {"input": (usage and usage.prompt_token_count) or 0,
              "output": (usage and usage.candidates_token_count) or 0,
              "thoughts": (usage and usage.thoughts_token_count) or 0}
    raw_text = response.text or ""
    result: dict = {"model": model, "duration_s": duration_s, "tokens": tokens, "raw_text": raw_text}
    try:
        parsed = json.loads(raw_text)
        result["parsed"] = parsed
    except json.JSONDecodeError as exc:
        parsed = None
        result["parse_error"] = str(exc)
    (out_dir / "response.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"  {duration_s} s  tokens in={tokens['input']} out={tokens['output']} thoughts={tokens['thoughts']}")
    if parsed is None:
        print(f"  INVALID JSON: {result['parse_error']}\n  raw: {raw_text[:300]}")
    else:
        print("  " + json.dumps(parsed, ensure_ascii=False))
        box = parsed.get("box_2d") if isinstance(parsed, dict) else None
        if box and len(box) == 4:
            img = cv2.imread(str(image_path))
            h, w = img.shape[:2]
            x1, y1, x2, y2 = box_to_pixels(box, w, h)
            cv2.rectangle(img, (x1, y1), (x2, y2), (0, 0, 255), 3)
            cv2.imwrite(str(out_dir / "boxed.jpg"), img)
    print(f"  -> {out_dir}")


if __name__ == "__main__":
    main()
