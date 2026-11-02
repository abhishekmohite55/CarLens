"""
Dev tool: probe one video + model to diagnose Gemini failures.
Run from F:\\CarLens\\backend:
    python -m scripts.probe_video <video_path> <model>

Steps:
1. Upload video via Files API, wait for ACTIVE, print full file object.
2. Ask model "Describe this video in one sentence." (no system prompt, no schema,
   default media resolution).
3. Print PASS/FAIL, reply or exact error, time taken.
4. Save output to runs/_checks/probe_<timestamp>.json.
"""
from __future__ import annotations

import json
import os
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
    if len(sys.argv) != 3:
        print("Usage: python -m scripts.probe_video <video_path> <model>")
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

    result = probe(video_path, model)
    verdict = result.get("verdict", "FAIL")
    print(f"\nVerdict: {verdict}")

    saved = _save(result)
    print(f"Saved: {saved}")
    print(sep)


if __name__ == "__main__":
    main()
