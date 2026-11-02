from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Callable

import google.genai as genai
from google.genai import types

log = logging.getLogger(__name__)

_POLL_INTERVAL = 5  # seconds between file state polls


def call_gemini_video(
    *,
    video_path: Path,
    system_prompt: str,
    user_prompt: str,
    model: str,
    temperature: float,
    media_resolution: str,
    timeout_sec: int,
    emit: Callable[[str], None],
) -> dict:
    """Upload video, wait for ACTIVE, ask model, return result dict."""
    client = genai.Client()

    # 1. Upload
    emit("Uploading video to Gemini")
    upload_file = client.files.upload(file=video_path)
    gemini_file_name = upload_file.name

    # 2. Poll until ACTIVE
    emit("Gemini processing video")
    deadline = time.monotonic() + timeout_sec
    last_state = None
    while True:
        info = client.files.get(name=gemini_file_name)
        state = info.state
        if state != last_state:
            emit(f"Gemini processing video")
            last_state = state
        if state == "ACTIVE":
            break
        if state == "FAILED":
            raise RuntimeError(f"Gemini file processing failed: {gemini_file_name}")
        if time.monotonic() > deadline:
            raise TimeoutError(
                f"Gemini file not ready after {timeout_sec}s (state: {state})"
            )
        time.sleep(_POLL_INTERVAL)

    # 3. Ask model
    emit("Asking Gemini")
    t0 = time.monotonic()

    res_map = {
        "low": "MEDIA_RESOLUTION_LOW",
        "medium": "MEDIA_RESOLUTION_MEDIUM",
        "high": "MEDIA_RESOLUTION_HIGH",
    }
    resolution = res_map.get(media_resolution.lower(), media_resolution.upper())

    response = client.models.generate_content(
        model=model,
        contents=[
            types.Part.from_text(text=user_prompt),
            types.Part.from_uri(file_uri=info.uri, mime_type=info.mime_type or "video/mp4"),
        ],
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=temperature,
            response_mime_type="application/json",
            media_resolution=resolution,
        ),
    )
    duration_ms = int((time.monotonic() - t0) * 1000)

    raw_text = response.text or ""
    usage = response.usage_metadata
    tokens_in = usage.prompt_token_count if usage else 0
    tokens_out = usage.candidates_token_count if usage else 0

    return {
        "raw_text": raw_text,
        "tokens": {"input": tokens_in, "output": tokens_out},
        "duration_ms": duration_ms,
        "gemini_file_name": gemini_file_name,
    }
