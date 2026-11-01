"""
Run from F:\\CarLens\\backend:
    python -m scripts.check_apis

Makes one real call to each external service. Prints PASS/FAIL per service.
Never prints API key values. GEMINI_MODEL is a model name (not secret) and is shown.
Results saved to runs/_checks/<timestamp>.json.
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


def _save(results: dict) -> None:
    CHECKS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = CHECKS_DIR / f"{ts}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\nResults saved: {path}")


# ─── Gemini ───────────────────────────────────────────────────────────────────

def _test_generate(client, model_name: str, label: str) -> dict:
    if not model_name:
        print(f"  {label}: no model — skip")
        return {"status": "skipped", "reason": "no model name"}
    t0 = time.perf_counter()
    try:
        resp = client.models.generate_content(
            model=model_name,
            contents="Reply with exactly: OK",
        )
        elapsed = round(time.perf_counter() - t0, 2)
        text = (resp.text or "").strip() if hasattr(resp, "text") else ""
        tokens: dict = {}
        if resp.usage_metadata:
            tokens = {
                "input": resp.usage_metadata.prompt_token_count,
                "output": resp.usage_metadata.candidates_token_count,
            }
        status = "pass" if text else "pass_empty_reply"
        print(f"  {label} ({model_name}): {status.upper()} in {elapsed}s "
              f"— reply: {text!r} — tokens: {tokens}")
        return {"status": status, "model": model_name, "reply": text,
                "elapsed_s": elapsed, "tokens": tokens}
    except Exception as exc:
        elapsed = round(time.perf_counter() - t0, 2)
        print(f"  {label} ({model_name}): FAIL in {elapsed}s — {exc}")
        return {"status": "fail", "model": model_name, "error": str(exc), "elapsed_s": elapsed}


def check_gemini(results: dict) -> None:
    api_key = os.environ.get("GEMINI_API_KEY", "")
    env_model = os.environ.get("GEMINI_MODEL", "")  # model name, not a secret

    if not api_key:
        print("GEMINI: FAIL — GEMINI_API_KEY not set in .env")
        results["gemini"] = {"status": "fail", "error": "GEMINI_API_KEY not set"}
        return

    from google import genai

    client = genai.Client(api_key=api_key)

    # List models that support content generation
    t0 = time.perf_counter()
    model_list = list(client.models.list())
    list_elapsed = round(time.perf_counter() - t0, 2)

    gen_models = [
        m.name for m in model_list
        if m.supported_actions and "generateContent" in m.supported_actions
    ]
    print(f"GEMINI: Listed {len(gen_models)} content-generation models in {list_elapsed}s:")
    for name in gen_models:
        print(f"  {name}")

    # First Flash model for fallback test
    flash_model = next(
        (m for m in gen_models if "flash" in m.lower()), None
    )

    # Test GEMINI_MODEL from .env
    # API returns names like "models/gemini-2.0-flash"; env may omit "models/" prefix
    env_in_list = (
        env_model in gen_models
        or f"models/{env_model}" in gen_models
        or any(m.endswith(f"/{env_model}") for m in gen_models)
    )
    print(f"\nGEMINI_MODEL from .env: {env_model!r}  (in generation list: {env_in_list})")
    env_result = _test_generate(client, env_model, "GEMINI_MODEL (.env)")

    print(f"\nFirst Flash model from list: {flash_model!r}")
    flash_result = _test_generate(client, flash_model, "First Flash model")

    results["gemini"] = {
        "status": "pass",
        "list_elapsed_s": list_elapsed,
        "generation_models": gen_models,
        "env_model": env_model,
        "env_model_in_list": env_in_list,
        "env_model_test": env_result,
        "flash_model": flash_model,
        "flash_model_test": flash_result,
    }


# ─── Tavily ───────────────────────────────────────────────────────────────────

def check_tavily(results: dict) -> None:
    api_key = os.environ.get("TAVILY_API_KEY", "")
    if not api_key:
        print("TAVILY: FAIL — TAVILY_API_KEY not set in .env")
        results["tavily"] = {"status": "fail", "error": "TAVILY_API_KEY not set"}
        return

    from tavily import TavilyClient

    client = TavilyClient(api_key=api_key)
    query = "used Maruti Suzuki Swift VXi 2019 price Pune"

    t0 = time.perf_counter()
    try:
        resp = client.search(query=query, max_results=3)
    except Exception as exc:
        elapsed = round(time.perf_counter() - t0, 2)
        print(f"TAVILY: FAIL in {elapsed}s — {exc}")
        results["tavily"] = {"status": "fail", "error": str(exc), "elapsed_s": elapsed}
        return

    elapsed = round(time.perf_counter() - t0, 2)
    items = resp.get("results", [])
    print(f"TAVILY: PASS in {elapsed}s — {len(items)} results")
    for r in items:
        has_content = bool(r.get("content") or r.get("raw_content"))
        print(f"  {r.get('title', '(no title)')}")
        print(f"    {r.get('url', '')}")
        print(f"    page content returned: {has_content}")

    results["tavily"] = {
        "status": "pass",
        "elapsed_s": elapsed,
        "query": query,
        "results": [
            {
                "title": r.get("title"),
                "url": r.get("url"),
                "has_content": bool(r.get("content") or r.get("raw_content")),
                "content_excerpt": (r.get("content") or r.get("raw_content") or "")[:300],
            }
            for r in items
        ],
    }


# ─── Langfuse ─────────────────────────────────────────────────────────────────

def check_langfuse(results: dict) -> None:
    pk = os.environ.get("LANGFUSE_PUBLIC_KEY", "")
    sk = os.environ.get("LANGFUSE_SECRET_KEY", "")
    host = os.environ.get("LANGFUSE_HOST", "https://cloud.langfuse.com")

    if not pk or not sk:
        print("LANGFUSE: FAIL — LANGFUSE_PUBLIC_KEY or LANGFUSE_SECRET_KEY not set")
        results["langfuse"] = {"status": "fail", "error": "Keys not set"}
        return

    try:
        from langfuse import Langfuse

        lf = Langfuse(public_key=pk, secret_key=sk, host=host)

        t0 = time.perf_counter()
        auth_ok = lf.auth_check()
        auth_elapsed = round(time.perf_counter() - t0, 2)

        if not auth_ok:
            print(f"LANGFUSE: FAIL — auth_check returned False in {auth_elapsed}s")
            results["langfuse"] = {"status": "fail", "error": "auth_check returned False",
                                   "host": host}
            return

        print(f"LANGFUSE: auth_check PASS in {auth_elapsed}s (host: {host})")

        # Send a tiny test trace named "carlens-check"
        t1 = time.perf_counter()
        span = lf.start_observation(
            name="carlens-check",
            as_type="span",
            input={"check": "api_connectivity"},
            output={"status": "ok"},
        )
        span.end()
        lf.flush()
        trace_elapsed = round(time.perf_counter() - t1, 2)

        print(f"LANGFUSE: trace 'carlens-check' flushed PASS in {trace_elapsed}s")
        results["langfuse"] = {
            "status": "pass",
            "host": host,
            "auth_elapsed_s": auth_elapsed,
            "trace_elapsed_s": trace_elapsed,
        }

    except Exception as exc:
        print(f"LANGFUSE: FAIL — {exc}")
        results["langfuse"] = {"status": "fail", "error": str(exc), "host": host}


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    results: dict = {
        "checked_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }

    sep = "=" * 60
    print(sep)
    print("CarLens API checks")
    print(sep)

    print("\n--- Gemini ---")
    try:
        check_gemini(results)
    except Exception as exc:
        print(f"GEMINI: ERROR — {exc}")
        results["gemini"] = {"status": "error", "error": str(exc)}

    print("\n--- Tavily ---")
    try:
        check_tavily(results)
    except Exception as exc:
        print(f"TAVILY: ERROR — {exc}")
        results["tavily"] = {"status": "error", "error": str(exc)}

    print("\n--- Langfuse ---")
    try:
        check_langfuse(results)
    except Exception as exc:
        print(f"LANGFUSE: ERROR — {exc}")
        results["langfuse"] = {"status": "error", "error": str(exc)}

    print(f"\n{sep}")
    _save(results)


if __name__ == "__main__":
    main()
