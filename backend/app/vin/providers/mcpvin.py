"""mcp.vin REST (free, no key; 30 requests / minute per IP): GET /api/vin/<VIN> → one nested JSON report
(recalls, complaints, safety ratings, EPA fuel economy, ...). Used for vehicle details (stage U4), not to decode."""
from __future__ import annotations

import os

import requests

from . import ProviderDown


def decode(vin: str, settings) -> dict:
    url = f"{settings.base_url.rstrip('/')}/{vin}"
    headers = {"Accept": "application/json"}
    if settings.key_env and os.environ.get(settings.key_env):
        headers["Authorization"] = f"Bearer {os.environ[settings.key_env]}"
    try:
        r = requests.get(url, timeout=settings.timeout_sec, headers=headers)
    except requests.RequestException as exc:
        raise ProviderDown(f"{type(exc).__name__}: {exc}") from exc
    if r.status_code != 200:
        raise ProviderDown(f"HTTP {r.status_code}")
    try:
        body = r.json()
    except ValueError as exc:
        raise ProviderDown("answer is not JSON") from exc
    if not isinstance(body, dict):
        raise ProviderDown("answer is not a JSON object")
    return body


def record(raw: dict) -> dict:
    return raw
