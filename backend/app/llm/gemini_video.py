from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Callable

import google.genai as genai
from google.genai import types
from google.genai.errors import APIError

log = logging.getLogger(__name__)

_POLL_INTERVAL = 5  # seconds between file state polls
_RETRYABLE_CODES = frozenset({429, 500, 503, 504})


def _is_retryable(exc: Exception) -> bool:
    return isinstance(exc, APIError) and exc.code in _RETRYABLE_CODES


def _generate(client, model: str, info, user_prompt: str, system_prompt: str,
              temperature: float, resolution: str, response_schema: dict | None,
              thinking_level: str | None = None) -> object:
    cfg_kwargs: dict = dict(
        system_instruction=system_prompt,
        temperature=temperature,
        response_mime_type="application/json",
        response_schema=response_schema,
        media_resolution=resolution,
    )
    if thinking_level:
        cfg_kwargs["thinking_config"] = types.ThinkingConfig(thinking_level=thinking_level)
    return client.models.generate_content(
        model=model,
        contents=[
            types.Part.from_text(text=user_prompt),
            types.Part.from_uri(file_uri=info.uri, mime_type=info.mime_type or "video/mp4"),
        ],
        config=types.GenerateContentConfig(**cfg_kwargs),
    )


def call_gemini_video(
    *,
    video_path: Path,
    system_prompt: str,
    user_prompt: str,
    model: str,
    fallback_model: str | None = None,
    temperature: float,
    media_resolution: str,
    timeout_sec: int,
    emit: Callable[[str], None],
    response_schema: dict | None = None,
    thinking_level: str | None = None,
) -> dict:
    """Upload video, wait for ACTIVE, ask model, return result dict.

    Returns dict with keys: raw_text, tokens, duration_ms, gemini_file_name,
    model_used, and optionally fallback={from, reason}.
    """
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
            emit("Gemini processing video")
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

    res_map = {
        "low": "MEDIA_RESOLUTION_LOW",
        "medium": "MEDIA_RESOLUTION_MEDIUM",
        "high": "MEDIA_RESOLUTION_HIGH",
    }
    resolution = res_map.get(media_resolution.lower(), media_resolution.upper())

    # 3. Ask model (with one fallback attempt on retryable errors)
    emit("Asking Gemini")
    t0 = time.monotonic()

    fallback_info: dict | None = None
    model_used = model

    try:
        response = _generate(client, model, info, user_prompt, system_prompt,
                             temperature, resolution, response_schema, thinking_level)
    except Exception as exc:
        if fallback_model and _is_retryable(exc):
            reason = f"{getattr(exc, 'code', '')} {getattr(exc, 'status', str(exc))}".strip()
            emit(f"{model} busy ({getattr(exc, 'code', 'error')}). Trying {fallback_model}")
            log.warning("locate main model %s failed (%s), trying fallback %s", model, reason, fallback_model)
            try:
                response = _generate(client, fallback_model, info, user_prompt, system_prompt,
                                     temperature, resolution, response_schema, thinking_level)
                fallback_info = {"from": model, "reason": reason}
                model_used = fallback_model
            except Exception as exc2:
                reason2 = f"{getattr(exc2, 'code', '')} {getattr(exc2, 'status', str(exc2))}".strip()
                raise RuntimeError(
                    f"Both models failed: {model} → {reason}; {fallback_model} → {reason2}"
                ) from exc2
        else:
            raise

    duration_ms = int((time.monotonic() - t0) * 1000)

    try:
        raw_text = response.text or ""
    except Exception as exc:
        log.warning("response.text raised %s; trying candidates", exc)
        try:
            raw_text = response.candidates[0].content.parts[0].text or ""
        except Exception:
            raw_text = ""
    usage = response.usage_metadata
    tokens_in = usage.prompt_token_count if usage else 0
    tokens_out = usage.candidates_token_count if usage else 0
    tokens_thoughts = (usage.thoughts_token_count or 0) if usage else 0

    result: dict = {
        "raw_text": raw_text,
        "tokens": {"input": tokens_in, "output": tokens_out, "thoughts": tokens_thoughts},
        "duration_ms": duration_ms,
        "gemini_file_name": gemini_file_name,
        "model_used": model_used,
    }
    if fallback_info:
        result["fallback"] = fallback_info
    return result
