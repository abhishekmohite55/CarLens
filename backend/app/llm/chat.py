from __future__ import annotations

import base64
import json
import logging
import re
import threading
import time
from pathlib import Path
from typing import Any, Callable

from langchain.chat_models import init_chat_model

log = logging.getLogger(__name__)

# Hardening A3: model calls still running in this process, also ones past their timeout (a timed-out thread
# keeps waiting for the provider). ask_chain refuses a new attempt when max_in_flight are running.
_in_flight = 0
_in_flight_lock = threading.Lock()


def claim_call(max_in_flight: int | None) -> bool:
    """Count one more running model call; False (nothing counted) when max_in_flight are already running."""
    global _in_flight
    with _in_flight_lock:
        if max_in_flight is not None and _in_flight >= max_in_flight:
            return False
        _in_flight += 1
        return True


def release_call() -> None:
    global _in_flight
    with _in_flight_lock:
        _in_flight = max(0, _in_flight - 1)


def calls_in_flight() -> int:
    with _in_flight_lock:
        return _in_flight


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


def own_settings(entry, chain_timeout: int, chain_temperature: float) -> tuple[int, float]:
    """(timeout, temperature) for one model: its own values when set, else the chain's."""
    timeout = getattr(entry, "timeout_sec", None)
    temperature = getattr(entry, "temperature", None)
    return (timeout if isinstance(timeout, (int, float)) and timeout > 0 else chain_timeout,
            temperature if isinstance(temperature, (int, float)) else chain_temperature)


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
    max_in_flight: int | None = None,  # hardening A3: models.max_calls_in_flight; None = no cap
) -> dict:
    """Try entries in order; per-model timeout enforced via daemon thread.

    Returns {"answered_by": {provider, model} | None, "attempts": [...], "parsed": ... | None}.
    Never raises for a model failure.
    """
    attempts: list[dict] = []
    answered_by = None
    parsed_result = None

    chain_temperature, chain_timeout = temperature, timeout_sec
    for n, entry in enumerate(entries, start=1):
        # a model's own timeout / temperature wins over the chain's (config.yaml models, step 6.3)
        timeout_sec, temperature = own_settings(entry, chain_timeout, chain_temperature)
        emit(f"[{n}/{len(entries)}] {entry.model}")
        attempt: dict = {"provider": entry.provider, "model": entry.model}
        if not claim_call(max_in_flight):
            attempt["error"] = f"not started: {max_in_flight} model calls are still running"
            emit(f"{entry.model} not started: too many model calls still running")
            attempts.append(attempt)
            continue
        box: dict = {}  # this attempt's own result; bound into the thread below, so a late thread never touches the next one
        t0 = time.perf_counter()

        def call(e=entry, temperature=temperature, timeout_sec=timeout_sec, box=box, t0=t0) -> None:
            try:
                msgs = build_messages(e)
                m = make_chat_model(e.provider, e.model, temperature, timeout_sec, thinking_level, reasoning_effort)
                cfg = {"callbacks": callbacks, "metadata": metadata or {}} if callbacks else {}
                box["msg"] = m.invoke(msgs, config=cfg)
            except Exception as exc:  # noqa: BLE001
                box["error"] = f"{type(exc).__name__}: {exc}"
            finally:
                release_call()
                if box.get("abandoned"):
                    log.warning("late answer from %s ignored: it came %.0f s after the call started",
                                e.model, time.perf_counter() - t0)

        worker = threading.Thread(target=call, daemon=True)
        worker.start()
        while worker.is_alive() and (left := timeout_sec - (time.perf_counter() - t0)) > 0:
            worker.join(min(15, left))

        attempt["seconds"] = round(time.perf_counter() - t0, 2)

        if worker.is_alive():
            box["abandoned"] = True  # the thread may still answer later: logged and ignored, never used
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
