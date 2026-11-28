"""NHTSA vPIC (free, no key): DecodeVinValuesExtended. One flat record per VIN in Results[0]."""
from __future__ import annotations

import os

import requests

from . import ProviderDown


def decode(vin: str, settings) -> dict:
    """settings: base_url, timeout_sec, key_env (vPIC needs no key; kept for the same config shape)."""
    url = f"{settings.base_url.rstrip('/')}/DecodeVinValuesExtended/{vin}"
    params = {"format": "json"}
    if settings.key_env and os.environ.get(settings.key_env):
        params["api_key"] = os.environ[settings.key_env]
    try:
        r = requests.get(url, params=params, timeout=settings.timeout_sec, headers={"Accept": "application/json"})
    except requests.RequestException as exc:
        raise ProviderDown(f"{type(exc).__name__}: {exc}") from exc
    if r.status_code != 200:
        raise ProviderDown(f"HTTP {r.status_code}")
    try:
        body = r.json()
    except ValueError as exc:
        raise ProviderDown("answer is not JSON") from exc
    if not isinstance(body, dict) or not isinstance(body.get("Results"), list):
        raise ProviderDown("answer has no Results")
    return body


def record(raw: dict) -> dict:
    results = raw.get("Results") or []
    return results[0] if results and isinstance(results[0], dict) else {}
