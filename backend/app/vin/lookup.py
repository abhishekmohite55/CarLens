"""VIN lookup with saved answers (table vin_lookups). The caller passes the vin config; nothing here reads config.

Same VIN within cache_days → the saved answer (car found or not found); no second call. A provider that is down is
saved too (for the record) but never reused. Rate limit: real provider calls per user in the last hour."""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, insert, or_, select

from ..db import require_engine
from ..models import VinLookup
from .check import normalise_vin, vin_problem
from .mapping import not_found_message, pick, to_common
from .providers import ProviderDown, provider_module


class VinError(Exception):
    """A lookup the user gets a message for. status: 422 vin_invalid / vin_not_found, 429 too_many,
    503 vin_unavailable."""

    def __init__(self, status: int, code: str, message: str, answer: dict | None = None):
        super().__init__(message)
        self.status, self.code, self.message, self.answer = status, code, message, answer


UNAVAILABLE = "VIN lookup is not working, please come back later."
TOO_MANY = "Too many VIN lookups. Try again in an hour."


def _saved(conn, vin: str, provider: str, cache_days: int):
    if cache_days <= 0:
        return None
    since = datetime.now(timezone.utc) - timedelta(days=cache_days)
    return conn.execute(select(VinLookup).where(
        VinLookup.vin == vin, VinLookup.provider == provider, VinLookup.created_at > since,
        or_(VinLookup.ok.is_(True), VinLookup.error == "not_found")).order_by(VinLookup.id.desc()).limit(1)).first()


def _calls_last_hour(conn, user_id: int | None) -> int:
    since = datetime.now(timezone.utc) - timedelta(hours=1)
    return conn.execute(select(func.count()).select_from(VinLookup).where(
        VinLookup.user_id == user_id, VinLookup.created_at > since)).scalar_one()


def _answer(row) -> dict:
    return {"vin": row.vin, "provider": row.provider, "car": row.car, "ok": row.ok, "error": row.error,
            "saved_at": row.created_at.isoformat(), "reused": True, "ms": row.ms}


def _finish(answer: dict) -> dict:
    if not answer["ok"]:
        raise VinError(422, "vin_not_found", not_found_message(answer["car"] or {}), answer)
    return answer


def lookup_vin(vin_text: str, user_id: int | None, vin_cfg, is_admin: bool = False) -> dict:
    """The common shape for a VIN the user typed (07-us-market.md §4.2), or VinError. vin_cfg: config `vin`."""
    vin = normalise_vin(vin_text)
    problem = vin_problem(vin)
    if problem:
        raise VinError(422, "vin_invalid", problem)
    provider = vin_cfg.provider
    engine = require_engine()
    with engine.connect() as conn:
        row = _saved(conn, vin, provider, vin_cfg.cache_days)
        if row is not None:
            return _finish(_answer(row))
        if not is_admin and _calls_last_hour(conn, user_id) >= vin_cfg.max_lookups_per_hour:
            raise VinError(429, "too_many", TOO_MANY)

    module = provider_module(provider)
    settings = vin_cfg.providers[provider]
    start = time.perf_counter()
    try:
        raw = module.decode(vin, settings)
        answer = to_common(vin, provider, pick(module.record(raw), settings.fields))
        failure = None
    except ProviderDown as exc:
        raw, answer, failure = None, None, str(exc)
    ms = round((time.perf_counter() - start) * 1000)

    with engine.begin() as conn:
        saved_id = conn.execute(insert(VinLookup).values(
            vin=vin, provider=provider, user_id=user_id, ms=ms,
            ok=bool(answer and answer["ok"]), error=(answer or {}).get("error") or ("unavailable" if failure else None),
            car=answer["car"] if answer else None, raw=raw if raw is not None else {"failure": failure})
            .returning(VinLookup.id)).scalar_one()
    if answer is None:
        raise VinError(503, "vin_unavailable", UNAVAILABLE)
    return _finish({**answer, "lookup_id": saved_id, "reused": False, "ms": ms})


def found_lookup(vin: str, provider: str, cache_days: int) -> dict | None:
    """Stage U2: the newest saved lookup of this VIN that found the car, within cache_days; None when there is none
    (the upload then asks to look the VIN up first). The server uses this row, never car values from the browser."""
    since = datetime.now(timezone.utc) - timedelta(days=max(cache_days, 0))
    with require_engine().connect() as conn:
        row = conn.execute(select(VinLookup).where(
            VinLookup.vin == vin, VinLookup.provider == provider, VinLookup.ok.is_(True),
            VinLookup.created_at > since).order_by(VinLookup.id.desc()).limit(1)).first()
    if row is None:
        return None
    return {"lookup_id": row.id, "vin": row.vin, "provider": row.provider, "car": row.car, "raw": row.raw,
            "ms": row.ms, "saved_at": row.created_at.isoformat()}
