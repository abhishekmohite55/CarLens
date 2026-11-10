"""
Dev tool: probe one video + model to diagnose Gemini failures.
Run from F:\\CarLens\\backend:
    python -m scripts.probe_video <video_path> <model>
    python -m scripts.probe_video <video_path> <model> medium,small,current

Plain mode (no 3rd arg):
1. Upload video via Files API, wait for ACTIVE, print full file object.
2. Ask model "Describe this video in one sentence." (no system prompt, no schema,
   default media resolution).
3. Print PASS/FAIL, reply or exact error, time taken.
4. Save output to runs/_checks/probe_<timestamp>.json.

Variants mode (3rd arg = comma-separated medium,small,current):
- Upload once, run each variant in order on the same Gemini file.
- medium: locate_medium.system.md, application/json, no schema.
- small:  locate_small.system.md,  application/json, no schema.
- current: locate.system.md,       application/json + _RESPONSE_SCHEMA.
- Save everything to runs/_checks/probe_<timestamp>.json.

Fast mode (3rd arg = fast):
    python -m scripts.probe_video <video_path> <model> fast
- Shrink with ffmpeg to 720p / 5 fps / no audio (runs/_checks/<name>_small.mp4).
  Needs `pip install imageio-ffmpeg` or ffmpeg on PATH.
- Send the small file via Files API (same as the pipeline), model default thinking.
- Current locate prompts + _RESPONSE_SCHEMA.
- Prints per-step timings, tokens (incl. thoughts) and validated items.
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).parent.parent.parent  # F:\CarLens
load_dotenv(PROJECT_ROOT / ".env")

CHECKS_DIR = PROJECT_ROOT / "runs" / "_checks"
_POLL_INTERVAL = 5  # seconds between file state polls


def _save(result: dict) -> Path:
    CHECKS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")[:20]
    path = CHECKS_DIR / f"probe_{ts}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    return path


def probe(video_path: Path, model: str) -> dict:
    import google.genai as genai
    from google.genai import types

    client = genai.Client()
    result: dict = {
        "probed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "video": str(video_path),
        "model": model,
    }

    # 1. Upload
    print(f"Uploading {video_path.name} …")
    t_upload = time.perf_counter()
    try:
        upload_file = client.files.upload(file=video_path)
    except Exception as exc:
        result["upload"] = {"status": "fail", "error": str(exc)}
        print(f"  UPLOAD FAIL: {exc}")
        return result
    elapsed_upload = round(time.perf_counter() - t_upload, 2)
    print(f"  uploaded in {elapsed_upload}s → {upload_file.name}")

    # 2. Poll until ACTIVE
    print("  Waiting for ACTIVE …")
    t_poll = time.perf_counter()
    gemini_file_name = upload_file.name
    file_info = None
    while True:
        info = client.files.get(name=gemini_file_name)
        if info.state == "ACTIVE":
            file_info = info
            break
        if info.state == "FAILED":
            result["upload"] = {
                "status": "fail",
                "error": f"file state=FAILED: {info}",
                "file_object": _file_obj(info),
            }
            print(f"  FILE FAILED: {info}")
            return result
        time.sleep(_POLL_INTERVAL)
    elapsed_poll = round(time.perf_counter() - t_poll, 2)

    file_obj = _file_obj(file_info)
    result["upload"] = {
        "status": "ok",
        "elapsed_upload_s": elapsed_upload,
        "elapsed_poll_s": elapsed_poll,
        "file_object": file_obj,
    }
    print(f"  ACTIVE in {elapsed_poll}s")
    print(f"  file object: {json.dumps(file_obj, indent=4)}")

    # 3. Ask model
    print(f"  Asking {model} …")
    t_gen = time.perf_counter()
    try:
        response = client.models.generate_content(
            model=model,
            contents=[
                types.Part.from_uri(
                    file_uri=file_info.uri,
                    mime_type=file_info.mime_type or "video/mp4",
                ),
                types.Part.from_text(text="Describe this video in one sentence."),
            ],
        )
        elapsed_gen = round(time.perf_counter() - t_gen, 2)
        try:
            reply = response.text or ""
        except Exception:
            reply = ""
        usage = response.usage_metadata
        tokens = {
            "input": usage.prompt_token_count if usage else 0,
            "output": usage.candidates_token_count if usage else 0,
        }
        print(f"  PASS in {elapsed_gen}s")
        print(f"  reply: {reply!r}")
        print(f"  tokens: {tokens}")
        result["generate"] = {
            "status": "pass",
            "elapsed_s": elapsed_gen,
            "reply": reply,
            "tokens": tokens,
        }
    except Exception as exc:
        elapsed_gen = round(time.perf_counter() - t_gen, 2)
        code = getattr(exc, "code", None)
        status = getattr(exc, "status", None)
        error_str = str(exc)
        print(f"  FAIL in {elapsed_gen}s — {error_str}")
        result["generate"] = {
            "status": "fail",
            "elapsed_s": elapsed_gen,
            "error": error_str,
            "code": code,
            "api_status": status,
        }

    result["verdict"] = "PASS" if result.get("generate", {}).get("status") == "pass" else "FAIL"
    return result


def probe_variants(video_path: Path, model: str, variants_str: str) -> dict:
    import cv2
    import google.genai as genai
    from google.genai import types

    from app.config import PROJECT_ROOT as APP_ROOT, get_config
    from app.nodes.locate import _RESPONSE_SCHEMA

    cfg = get_config()
    temperature = cfg.models.temperature
    resolution_raw = cfg.models.locate_media_resolution
    res_map = {
        "low": "MEDIA_RESOLUTION_LOW",
        "medium": "MEDIA_RESOLUTION_MEDIUM",
        "high": "MEDIA_RESOLUTION_HIGH",
    }
    resolution = res_map.get(resolution_raw.lower(), resolution_raw.upper())

    # Read duration_sec via OpenCV
    cap = cv2.VideoCapture(str(video_path))
    opened = cap.isOpened()
    fps = cap.get(cv2.CAP_PROP_FPS) if opened else 0.0
    frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT) if opened else 0.0
    cap.release()
    duration_sec = round(frame_count / fps, 1) if fps > 0 else 0.0

    prompts_dir = APP_ROOT / cfg.paths.prompts_dir
    probe_dir = prompts_dir / "probe"

    from app.timecode import seconds_to_mmss
    user_prompt = (
        (prompts_dir / "locate.user.md").read_text(encoding="utf-8")
        .replace("{duration_sec}", str(duration_sec))
        .replace("{duration_mmss}", seconds_to_mmss(duration_sec))
    )

    variant_configs = {
        "medium": {
            "system_prompt_path": probe_dir / "locate_medium.system.md",
            "response_schema": None,
        },
        "small": {
            "system_prompt_path": probe_dir / "locate_small.system.md",
            "response_schema": None,
        },
        "current": {
            "system_prompt_path": prompts_dir / "locate.system.md",
            "response_schema": _RESPONSE_SCHEMA,
        },
    }

    variants = [v.strip() for v in variants_str.split(",")]

    client = genai.Client()
    result: dict = {
        "probed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "video": str(video_path),
        "model": model,
        "duration_sec": duration_sec,
        "variants": {},
    }

    # Upload once
    print(f"Uploading {video_path.name} …")
    t_upload = time.perf_counter()
    try:
        upload_file = client.files.upload(file=video_path)
    except Exception as exc:
        result["upload"] = {"status": "fail", "error": str(exc)}
        print(f"  UPLOAD FAIL: {exc}")
        return result
    elapsed_upload = round(time.perf_counter() - t_upload, 2)
    print(f"  uploaded in {elapsed_upload}s → {upload_file.name}")

    print("  Waiting for ACTIVE …")
    t_poll = time.perf_counter()
    gemini_file_name = upload_file.name
    file_info = None
    while True:
        info = client.files.get(name=gemini_file_name)
        if info.state == "ACTIVE":
            file_info = info
            break
        if info.state == "FAILED":
            result["upload"] = {"status": "fail", "error": f"file state=FAILED: {info}"}
            print(f"  FILE FAILED: {info}")
            return result
        time.sleep(_POLL_INTERVAL)
    elapsed_poll = round(time.perf_counter() - t_poll, 2)
    print(f"  ACTIVE in {elapsed_poll}s")

    result["upload"] = {
        "status": "ok",
        "elapsed_upload_s": elapsed_upload,
        "elapsed_poll_s": elapsed_poll,
        "gemini_file_name": gemini_file_name,
    }

    summary_parts: list[str] = []

    for variant_name in variants:
        if variant_name not in variant_configs:
            print(f"\n[{variant_name}] unknown variant, skipping")
            continue

        vcfg = variant_configs[variant_name]
        system_prompt = vcfg["system_prompt_path"].read_text(encoding="utf-8")
        response_schema = vcfg["response_schema"]

        print(f"\n--- {variant_name} ---")
        print(f"  system prompt: {vcfg['system_prompt_path'].name}")
        print(f"  schema: {'yes' if response_schema else 'no'}")

        t_gen = time.perf_counter()
        vresult: dict = {
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
            "settings": {
                "model": model,
                "temperature": temperature,
                "media_resolution": resolution_raw,
                "response_schema": response_schema is not None,
            },
        }
        try:
            response = client.models.generate_content(
                model=model,
                contents=[
                    types.Part.from_text(text=user_prompt),
                    types.Part.from_uri(
                        file_uri=file_info.uri,
                        mime_type=file_info.mime_type or "video/mp4",
                    ),
                ],
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    temperature=temperature,
                    response_mime_type="application/json",
                    response_schema=response_schema,
                    media_resolution=resolution,
                ),
            )
            elapsed_gen = round(time.perf_counter() - t_gen, 2)
            try:
                raw_reply = response.text or ""
            except Exception:
                raw_reply = ""
            usage = response.usage_metadata
            tokens = {
                "input": usage.prompt_token_count if usage else 0,
                "output": usage.candidates_token_count if usage else 0,
            }

            parsed = None
            json_ok = False
            item_count = 0
            by_category: dict[str, int] = {}
            try:
                parsed = json.loads(raw_reply)
                json_ok = True
                items = parsed.get("items", []) if isinstance(parsed, dict) else []
                item_count = len(items)
                for item in items:
                    cat = item.get("category", "unknown")
                    by_category[cat] = by_category.get(cat, 0) + 1
            except Exception:
                pass

            vresult.update({
                "status": "pass",
                "elapsed_s": elapsed_gen,
                "tokens": tokens,
                "raw_reply": raw_reply,
                "json_parsed": json_ok,
                "item_count": item_count,
                "items_by_category": by_category,
                "parsed": parsed,
                "error": None,
            })

            print(f"  PASS in {elapsed_gen}s")
            print(f"  tokens: {tokens}")
            print(f"  JSON parsed: {json_ok}, items: {item_count}, by category: {by_category}")
            print(f"  raw reply (first 300): {raw_reply[:300]!r}")
            summary_parts.append(f"{variant_name} PASS {elapsed_gen}s {item_count} items")

        except Exception as exc:
            elapsed_gen = round(time.perf_counter() - t_gen, 2)
            code = getattr(exc, "code", None)
            error_str = str(exc)
            print(f"  FAIL in {elapsed_gen}s — {error_str}")
            code_str = f" {code}" if code else ""
            vresult.update({
                "status": "fail",
                "elapsed_s": elapsed_gen,
                "tokens": None,
                "raw_reply": None,
                "json_parsed": False,
                "item_count": 0,
                "items_by_category": {},
                "parsed": None,
                "error": error_str,
                "code": code,
            })
            summary_parts.append(f"{variant_name} FAIL{code_str} in {elapsed_gen}s")

        result["variants"][variant_name] = vresult

    summary = " | ".join(summary_parts)
    print(f"\n{summary}")
    result["summary"] = summary
    return result


# ─── fast mode: shrink then the same Files API call as the pipeline ──────────

def probe_fast(video_path: Path, model: str) -> dict:
    import cv2

    from app.config import PROJECT_ROOT as APP_ROOT, get_config
    from app.llm.gemini_video import call_gemini_video
    from app.nodes.locate import _RESPONSE_SCHEMA, _validate_locate_items
    from app.timecode import seconds_to_mmss
    from app.video import shrink_video

    cfg = get_config()
    temperature = cfg.models.temperature
    resolution_raw = cfg.models.locate_media_resolution
    thinking_level = cfg.models.locate_thinking_level
    lv = cfg.locate_video

    # Duration of the ORIGINAL video (timestamps must match it for frames)
    cap = cv2.VideoCapture(str(video_path))
    fps_cap = cap.get(cv2.CAP_PROP_FPS) if cap.isOpened() else 0.0
    frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT) if cap.isOpened() else 0.0
    cap.release()
    duration_sec = round(frame_count / fps_cap, 1) if fps_cap > 0 else 0.0

    prompts_dir = APP_ROOT / cfg.paths.prompts_dir
    system_prompt = (prompts_dir / "locate.system.md").read_text(encoding="utf-8")
    user_prompt = (
        (prompts_dir / "locate.user.md").read_text(encoding="utf-8")
        .replace("{duration_sec}", str(duration_sec))
        .replace("{duration_mmss}", seconds_to_mmss(duration_sec))
    )

    t_total = time.perf_counter()
    result: dict = {
        "probed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "mode": "fast",
        "video": str(video_path),
        "original_mb": round(video_path.stat().st_size / 1e6, 1),
        "duration_sec": duration_sec,
        "model": model,
        "settings": {
            "shrink": {"height": lv.height, "fps": lv.fps, "crf": lv.crf},
            "media_resolution": resolution_raw,
            "temperature": temperature,
            "thinking_level": thinking_level,
        },
        "timings_s": {},
    }

    # 1. Shrink
    CHECKS_DIR.mkdir(parents=True, exist_ok=True)
    small_path = CHECKS_DIR / f"{video_path.stem}_small.mp4"
    print(f"Shrinking {video_path.name} ({result['original_mb']} MB) …")
    t = time.perf_counter()
    try:
        shrink_video(video_path, small_path, height=lv.height, fps=lv.fps, crf=lv.crf)
    except RuntimeError as exc:
        result["error"] = str(exc)
        print(f"  {result['error']}")
        return result
    result["timings_s"]["shrink"] = round(time.perf_counter() - t, 2)
    result["small_mb"] = round(small_path.stat().st_size / 1e6, 1)
    result["small_path"] = str(small_path)
    print(f"  {result['small_mb']} MB in {result['timings_s']['shrink']}s → {small_path.name}")

    # 2. Files API upload + ask via the same pipeline call
    msgs: list[str] = []

    def _emit(msg: str) -> None:
        msgs.append(msg)
        print(f"  {msg}")

    t_send = time.perf_counter()
    try:
        print(f"  Asking {model} (media_resolution={resolution_raw}) …")
        call_result = call_gemini_video(
            video_path=small_path,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=model,
            fallback_model=None,
            temperature=temperature,
            media_resolution=resolution_raw,
            timeout_sec=cfg.models.timeout_sec,
            emit=_emit,
            response_schema=_RESPONSE_SCHEMA,
            thinking_level=thinking_level,
        )
    except Exception as exc:
        result["timings_s"]["send_and_generate"] = round(time.perf_counter() - t_send, 2)
        result["timings_s"]["total"] = round(time.perf_counter() - t_total, 2)
        result["error"] = str(exc)
        result["code"] = getattr(exc, "code", None)
        print(f"  FAIL — {exc}")
        return result

    result["timings_s"]["generate"] = round(call_result["duration_ms"] / 1000, 2)
    result["timings_s"]["send_and_generate"] = round(time.perf_counter() - t_send, 2)
    result["timings_s"]["upload_and_active"] = round(
        result["timings_s"]["send_and_generate"] - result["timings_s"]["generate"], 2
    )
    result["timings_s"]["total"] = round(time.perf_counter() - t_total, 2)

    raw_reply = call_result["raw_text"]
    result["tokens"] = call_result["tokens"]
    result["raw_reply"] = raw_reply

    # Same checks the locate node applies
    try:
        parsed = json.loads(raw_reply)
        parsed["items"] = _validate_locate_items(parsed["items"], duration_sec)
        result["parsed"] = parsed
        result["validation"] = "ok"
    except Exception as exc:
        result["parsed"] = None
        result["validation"] = f"fail: {exc}"

    by_cat: dict[str, int] = {}
    for item in (result["parsed"] or {}).get("items", []):
        by_cat[item["category"]] = by_cat.get(item["category"], 0) + 1

    print(f"  timings: {result['timings_s']}")
    print(f"  tokens: {result['tokens']}")
    print(f"  validation: {result['validation']}, items by category: {by_cat}")
    if result["parsed"]:
        for item in result["parsed"]["items"]:
            t_text = item.get("t_text", "")
            print(f"    t={item['t']:>7.1f}s ({t_text})  {item['category']:<12} {item['side']:<9} {item['label']}")
        print(f"  coverage: {result['parsed'].get('coverage')}")
    else:
        print(f"  raw reply (first 500): {raw_reply[:500]!r}")
    return result


def _file_obj(info) -> dict:
    """Extract serialisable fields from a Gemini File object."""
    return {
        "name": getattr(info, "name", None),
        "state": str(getattr(info, "state", None)),
        "mime_type": getattr(info, "mime_type", None),
        "size_bytes": getattr(info, "size_bytes", None),
        "error": str(getattr(info, "error", None)) if getattr(info, "error", None) else None,
        "video_metadata": str(getattr(info, "video_metadata", None)),
        "uri": getattr(info, "uri", None),
    }


def main() -> None:
    if len(sys.argv) not in (3, 4):
        print("Usage: python -m scripts.probe_video <video_path> <model> [variants]")
        print("       variants: comma-separated medium,small,current, or fast (omit for plain probe)")
        sys.exit(1)

    video_path = Path(sys.argv[1])
    model = sys.argv[2]

    if not video_path.exists():
        print(f"Error: video not found: {video_path}")
        sys.exit(1)

    sep = "=" * 60
    print(sep)
    print(f"probe_video: {video_path.name} / {model}")
    print(sep)

    if len(sys.argv) == 4 and sys.argv[3] == "fast":
        result = probe_fast(video_path, model)
    elif len(sys.argv) == 4:
        result = probe_variants(video_path, model, sys.argv[3])
    else:
        result = probe(video_path, model)
        print(f"\nVerdict: {result.get('verdict', 'FAIL')}")

    saved = _save(result)
    print(f"Saved: {saved}")
    print(sep)


if __name__ == "__main__":
    main()
