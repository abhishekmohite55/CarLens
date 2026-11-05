from __future__ import annotations

import base64
import json
import re
import threading
import time
from pathlib import Path
from typing import Any, Callable

from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage, SystemMessage


def make_chat_model(provider: str, model: str, temperature: float, timeout_sec: int,
                    thinking_level: str | None, reasoning_effort: str | None = None):
    if provider == "google_genai":
        extra = {"thinking_level": thinking_level} if thinking_level else {}
        return init_chat_model(model, model_provider=provider, temperature=temperature,
                               timeout=timeout_sec, max_retries=1,
                               response_mime_type="application/json", **extra)
    if provider == "openrouter":
        extra = {"reasoning": {"effort": reasoning_effort}} if reasoning_effort else {}
        return init_chat_model(model, model_provider=provider, temperature=temperature,
                               timeout=timeout_sec * 1000, max_retries=0, **extra)
    raise ValueError(f"unknown provider {provider!r}")


def image_blocks(user_prompt: str, frames: list[dict], folder: Path,
                 media_resolution: str | None) -> list[dict]:
    content: list[dict] = [{"type": "text", "text": user_prompt}]
    for f in frames:
        content.append({"type": "text",
                        "text": f'Frame {f["file"]}: item {f["item_id"]}, {f["category"]}, "{f["label"]}"'})
        block: dict[str, Any] = {
            "type": "image",
            "mime_type": "image/jpeg",
            "base64": base64.b64encode((folder / f["file"]).read_bytes()).decode("ascii"),
        }
        if media_resolution is not None:
            block["media_resolution"] = f"MEDIA_RESOLUTION_{media_resolution.upper()}"
        content.append(block)
    return content


def parse_json(raw: str) -> dict:
    text = raw.strip()
    m = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
    return json.loads(m.group(1) if m else text)


def ask_chain(
    entries,
    build_messages: Callable,
    *,
    temperature: float,
    timeout_sec: int,
    thinking_level: str | None,
    validate: Callable[[dict], str | None],
    emit: Callable[[str], None],
    callbacks: list,
    metadata: dict | None = None,
    normalise: Callable[[Any], tuple[Any, list[str]]] | None = None,
    reasoning_effort: str | None = None,  # OpenRouter entries only (thinking_level is Gemini only)
) -> dict:
    """Try entries in order; per-model timeout enforced via daemon thread.

    Returns {"answered_by": {provider, model} | None, "attempts": [...], "parsed": ... | None}.
    Never raises for a model failure.
    """
    attempts: list[dict] = []
    answered_by = None
    parsed_result = None

    for n, entry in enumerate(entries, start=1):
        emit(f"[{n}/{len(entries)}] {entry.model}")
        attempt: dict = {"provider": entry.provider, "model": entry.model}
        box: dict = {}

        def call(e=entry) -> None:
            try:
                msgs = build_messages(e)
                m = make_chat_model(e.provider, e.model, temperature, timeout_sec, thinking_level, reasoning_effort)
                cfg = {"callbacks": callbacks, "metadata": metadata or {}} if callbacks else {}
                box["msg"] = m.invoke(msgs, config=cfg)
            except Exception as exc:  # noqa: BLE001
                box["error"] = f"{type(exc).__name__}: {exc}"

        t0 = time.perf_counter()
        worker = threading.Thread(target=call, daemon=True)
        worker.start()
        while worker.is_alive() and (left := timeout_sec - (time.perf_counter() - t0)) > 0:
            worker.join(min(15, left))

        attempt["seconds"] = round(time.perf_counter() - t0, 2)

        if worker.is_alive():
            attempt["error"] = f"no answer within {timeout_sec} s"
            emit(f"{entry.model} failed: no answer within {timeout_sec} s")
            attempts.append(attempt)
            continue

        if "error" in box:
            attempt["error"] = box["error"]
            emit(f"{entry.model} failed: {box['error'][:120]}")
            attempts.append(attempt)
            continue

        msg = box["msg"]
        usage = msg.usage_metadata or {}
        attempt["tokens"] = {
            "input": usage.get("input_tokens", 0),
            "output": usage.get("output_tokens", 0),
            "reasoning": usage.get("output_token_details", {}).get("reasoning", 0),
        }
        attempt["raw_text"] = msg.text

        try:
            parsed = parse_json(msg.text)
        except json.JSONDecodeError as exc:
            attempt["error"] = f"invalid JSON: {exc}"
            emit(f"{entry.model} failed: invalid JSON")
            attempts.append(attempt)
            continue

        if normalise is not None:
            parsed, repairs = normalise(parsed)
            if repairs:
                attempt["repairs"] = repairs
                emit(f"{entry.model}: answer repaired ({'; '.join(repairs)})"[:200])

        err = validate(parsed)
        if err:
            attempt["error"] = f"invalid answer: {err}"
            emit(f"{entry.model} failed: {err}")
            attempts.append(attempt)
            continue

        answered_by = {"provider": entry.provider, "model": entry.model}
        parsed_result = parsed
        attempts.append(attempt)
        break

    return {"answered_by": answered_by, "attempts": attempts, "parsed": parsed_result}
