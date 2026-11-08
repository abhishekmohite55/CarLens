from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

_client = None
_disabled = False


def _get_client():
    global _client, _disabled
    if _disabled:
        return None
    if _client is not None:
        return _client
    try:
        from langfuse import Langfuse
        _client = Langfuse()
        _client.auth_check()
        return _client
    except Exception as exc:
        log.warning("Langfuse tracing disabled: %s", exc)
        _disabled = True
        return None


def langchain_callbacks(run_id: str, node: str) -> list:
    """LangChain CallbackHandler for Langfuse, or [] when unavailable."""
    lf = _get_client()
    if lf is None:
        return []
    try:
        from langfuse.langchain import CallbackHandler  # langfuse 5.x path; session id goes in invoke metadata
        return [CallbackHandler()]
    except Exception as exc:
        log.warning("Langfuse langchain_callbacks failed: %s", exc)
        return []


def trace_locate(
    *,
    run_id: str,
    model: str,
    request_data: dict,
    raw_text: str,
    tokens: dict,
) -> None:
    lf = _get_client()
    if lf is None:
        return
    try:
        import langfuse
        with langfuse.propagate_attributes(session_id=run_id):
            gen = lf.start_observation(
                name="locate",
                as_type="generation",
                model=model,
                input=request_data,
                usage_details={"input": tokens.get("input", 0), "output": tokens.get("output", 0)},
            )
            gen.update(output=raw_text)
            gen.end()
        lf.flush()
    except Exception as exc:
        log.warning("Langfuse trace_locate failed: %s", exc)
