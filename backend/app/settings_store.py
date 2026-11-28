"""Config and prompts in the database (platform step 6.3, docs/platform/06-admin.md §6.1–6.3).

Every save is a new version; the newest is active. config.yaml and prompts/*.md are only the seed (version 1)
and the source for "Import from file". A run is pinned to the versions active when it starts.
"""
from __future__ import annotations

import logging
import string
import time
from threading import Lock
from typing import Any

import yaml
from pydantic import ValidationError
from sqlalchemy import func, insert, select, update
from sqlalchemy.exc import SQLAlchemyError

from . import config as config_mod
from .db import get_engine, require_engine
from .market import MARKETS, US_NODES, move_market_keys
from .models import AuditLog, ConfigVersion, PromptVersion, Run, User

log = logging.getLogger(__name__)

CHECK_EVERY_SEC = 5  # how often the active version is looked up again
PROVIDERS = ("google_genai", "openrouter")
# Prompts filled with str.format: only these {fields} may appear; write {{ and }} for literal braces.
FORMAT_FIELDS = {
    "verify.user.md": {"frame_count", "vin_car"},  # vin_car: US prompt only (owner 27 Nov: video vs VIN check)
    "photos.user.md": {"photo_count"},
    "extract_prices.user.md": {"trimmed_text"},
    "extract_labels.user.md": {"car_text", "trimmed_text"},  # stage E1: labelled extract
    "plan_searches.user.md": {"car_json", "damage_count", "damage_json", "tyre_count", "tyres_json", "queries_per_part"},
}

_lock = Lock()
_active_config: tuple[float, int, dict] | None = None  # (checked at, version id, data)
_config_by_id: dict[int, dict] = {}
_active_prompts: dict[str, tuple[float, dict[str, int]]] = {}  # market → (checked at, {name: version id})
_prompt_by_id: dict[int, str] = {}
_run_pins: dict[str, tuple[int | None, dict | None, str]] = {}  # run → (config id, prompt ids, market)


class SettingsError(Exception):
    """A config or prompt the admin tried to save was refused. problems: [{"field", "message"}]."""

    def __init__(self, problems: list[dict]):
        super().__init__("; ".join(f"{p['field']}: {p['message']}" for p in problems))
        self.problems = problems


def forget_cache() -> None:
    global _active_config
    with _lock:
        _active_config = None
        _active_prompts.clear()
        _run_pins.clear()


# --- pure checks ---

def check_config(data: Any, nodes: list[str], keep_origin: str | None = None) -> tuple[dict | None, list[dict]]:
    """The checked config as a plain dict (defaults filled in), or the list of problems. Same rules as the file
    (AppConfig) plus a few the types cannot express."""
    try:
        cfg = config_mod.AppConfig(**data)
    except ValidationError as exc:
        return None, [{"field": ".".join(str(part) for part in e["loc"]), "message": e["msg"]} for e in exc.errors()]
    except TypeError:
        return None, [{"field": "config", "message": "must be an object with the config sections"}]
    problems: list[dict] = []

    def bad(field: str, message: str) -> None:
        problems.append({"field": field, "message": message})

    m = cfg.models
    if m.locate.provider != "google_genai":
        bad("models.locate.provider", "locate sends the video with the Google SDK: provider must be google_genai")
    chains = {"locate": [m.locate], "verify_chain": m.verify_chain, "photos_chain": m.photos_chain,
              "plan_chain": m.plan_chain, "extract_chain": m.extract_chain}
    for name, entries in chains.items():
        if not entries and name != "photos_chain":  # empty photos_chain = use verify_chain
            bad(f"models.{name}", "needs at least one model")
        for i, e in enumerate(entries):
            where = f"models.{name}" if name == "locate" else f"models.{name}.{i}"
            if e.provider not in PROVIDERS:
                bad(f"{where}.provider", f"must be one of {', '.join(PROVIDERS)}")
            if not e.model.strip():
                bad(f"{where}.model", "model name is empty")
            if e.timeout_sec is not None and e.timeout_sec <= 0:
                bad(f"{where}.timeout_sec", "must be above 0 (or empty for the default)")
            if e.temperature is not None and not 0 <= e.temperature <= 2:
                bad(f"{where}.temperature", "must be between 0 and 2 (or empty for the default)")
    for field in ("timeout_sec", "verify_timeout_per_model_sec", "photos_timeout_per_model_sec",
                  "plan_timeout_per_model_sec", "extract_timeout_per_model_sec"):
        if getattr(m, field) <= 0:
            bad(f"models.{field}", "must be above 0")
    if not 0 <= m.temperature <= 2:
        bad("models.temperature", "must be between 0 and 2")
    if not cfg.upload.allowed_types:
        bad("upload.allowed_types", "needs at least one type")
    for field in ("max_size_mb", "max_duration_sec", "pending_minutes"):
        if getattr(cfg.upload, field) <= 0:
            bad(f"upload.{field}", "must be above 0")
    if cfg.dev.stop_after and cfg.dev.stop_after not in nodes:
        bad("dev.stop_after", f"must be empty or one of {', '.join(nodes)}")
    if cfg.dev.stop_after_us and cfg.dev.stop_after_us not in US_NODES:
        bad("dev.stop_after_us", f"must be empty or one of {', '.join(US_NODES)}")
    for market in cfg.dev.markets_on:
        if market not in MARKETS:
            bad(f"dev.markets_on.{market}", f"unknown market; markets: {', '.join(MARKETS)}")
    if cfg.markets.default not in MARKETS:
        bad("markets.default", f"must be one of {', '.join(MARKETS)}")
    for country, market in cfg.markets.country_map.items():
        if market not in MARKETS:
            bad(f"markets.country_map.{country}", f"must be one of {', '.join(MARKETS)}")
    for market in MARKETS:
        limits = cfg.markets.of(market).extract_limits
        if not 0 < limits.listing_min < limits.listing_max:
            bad(f"markets.{market}.extract_limits", "listing_min must be above 0 and below listing_max")
        mc = cfg.markets.of(market)
        if mc.extract_mode not in ("classic", "labels"):
            bad(f"markets.{market}.extract_mode", "must be classic or labels")
        if not 0 <= mc.light_repair_band.min < mc.light_repair_band.max:
            bad(f"markets.{market}.light_repair_band", "min must be 0 or more and below max")
    if cfg.markets.us.vin_mismatch_action not in ("stop", "warn"):
        bad("markets.us.vin_mismatch_action", "must be stop or warn")
    from .vin.providers import DETAILS as DETAILS_PROVIDERS, KNOWN as VIN_PROVIDERS  # stage U1, U4
    details = cfg.vin.details_provider
    if details and (details not in DETAILS_PROVIDERS or details not in cfg.vin.providers):
        bad("vin.details_provider", f"must be empty or one of {', '.join(DETAILS_PROVIDERS)} with an entry in vin.providers")
    if cfg.vin.provider not in VIN_PROVIDERS:
        bad("vin.provider", f"must be one of {', '.join(VIN_PROVIDERS)}")
    elif cfg.vin.provider not in cfg.vin.providers:
        bad("vin.providers", f"needs an entry for {cfg.vin.provider}")
    else:
        missing = sorted({"make", "model", "year"} - set(cfg.vin.providers[cfg.vin.provider].fields))
        if missing:
            bad(f"vin.providers.{cfg.vin.provider}.fields", f"needs {', '.join(missing)}")
    if cfg.auth.session_hours <= 0 or cfg.auth.max_failed_logins <= 0 or cfg.auth.lockout_minutes <= 0:
        bad("auth", "session_hours, max_failed_logins and lockout_minutes must be above 0")
    if keep_origin and keep_origin.rstrip("/") not in {o.rstrip("/") for o in cfg.auth.allowed_origins}:
        bad("auth.allowed_origins", f"must keep {keep_origin} (the address you are using now), or you lock yourself out")
    if cfg.access.default_tokens < 0:
        bad("access.default_tokens", "cannot be below 0")
    return (None, problems) if problems else (cfg.model_dump(), [])


def check_prompt(name: str, text: str) -> list[dict]:
    """Problems of a prompt text. Prompts filled with str.format may only use their known {fields}."""
    if not text.strip():
        return [{"field": name, "message": "the prompt is empty"}]
    allowed = FORMAT_FIELDS.get(name)
    if allowed is None:
        return []
    try:
        used = {field.split(".")[0].split("[")[0] for _, field, _, _ in string.Formatter().parse(text) if field is not None}
    except ValueError as exc:
        return [{"field": name, "message": f"unmatched {{ or }} ({exc}); write {{{{ and }}}} for literal braces"}]
    unknown = sorted(used - allowed)
    if unknown:
        return [{"field": name, "message": f"unknown placeholder(s) {', '.join('{' + u + '}' for u in unknown)}; "
                                           f"allowed: {', '.join('{' + a + '}' for a in sorted(allowed))}"}]
    return []


# --- files (the seed) ---

def _file_config_data() -> dict:
    with open(config_mod.CONFIG_PATH, encoding="utf-8") as f:
        return config_mod.AppConfig(**yaml.safe_load(f)).model_dump()


DEEPER_SECTIONS = ("markets",)  # stage M0: one level more, so markets.us.<field> is filled too
WHOLE_MAPS = ("country_map",)  # a map the owner edits as a whole: only added when missing, never topped up


def fill_defaults(data: dict, defaults: dict, depth: int = 2) -> tuple[dict, list[str]]:
    """data with every section / field of defaults it lacks added (two levels: sections and their fields; three for
    DEEPER_SECTIONS; values the owner set are never changed). Returns (new data, names added such as "maintenance" or
    "auth.client_ip_header")."""
    out, added = dict(data), []
    for key, value in defaults.items():
        if key not in out:
            out[key] = value
            added.append(key)
        elif depth > 1 and key not in WHOLE_MAPS and isinstance(value, dict) and isinstance(out[key], dict):
            out[key], sub = fill_defaults(out[key], value, depth if key in DEEPER_SECTIONS else depth - 1)
            added += [f"{key}.{name}" for name in sub]
    return out, added


def add_missing_settings(nodes: list[str]) -> str | None:
    """Startup (step 9.3): settings this code knows but the active config version lacks are saved as a new version,
    with their config.yaml values. Returns a note, or None when nothing was missing.
    Stage M0: a version from before markets has its India keys moved under markets.in first (so its own values are
    kept, not replaced by config.yaml's), and markets.<market>.<field> is filled too (DEEPER_SECTIONS)."""
    active = active_config()
    if active is None:
        return None
    data, added = fill_defaults(move_market_keys(active[1]), _file_config_data())
    if not added:
        return None
    checked, problems = check_config(data, nodes)
    if problems:
        raise SettingsError(problems)
    checked = {**data, **checked}  # sections an older code version does not know are kept, not dropped
    note = f"auto: added {', '.join(added)} (defaults)"
    with require_engine().begin() as conn:
        version_id = conn.execute(insert(ConfigVersion).values(data=checked, created_by=None, note=note)
                                  .returning(ConfigVersion.id)).scalar_one()
        conn.execute(insert(AuditLog).values(admin_id=None, action="auto_config", target=f"config version {version_id}",
                                             details={"added": added}))
    return note


def _prompts_dir(market: str = "in"):
    """prompts/<market>/ (stage M0: prompts/in/ = India, prompts/us/ = US)."""
    return config_mod.PROJECT_ROOT / config_mod.file_config().paths.prompts_dir / market


def _prompt_files(market: str = "in") -> dict[str, str]:
    return {p.name: p.read_text(encoding="utf-8") for p in sorted(_prompts_dir(market).glob("*.md"))}


# --- active versions ---

def active_config() -> tuple[int, dict] | None:
    """(version id, data) of the newest config version; seeds version 1 from config.yaml when the table is empty.
    None without a database, or when it cannot be read and nothing is cached (the caller uses the file)."""
    global _active_config
    engine = get_engine()
    if engine is None:
        return None
    with _lock:
        if _active_config and time.monotonic() - _active_config[0] < CHECK_EVERY_SEC:
            return _active_config[1], _active_config[2]
        try:
            with engine.begin() as conn:
                row = conn.execute(select(ConfigVersion.id, ConfigVersion.data)
                                   .order_by(ConfigVersion.id.desc()).limit(1)).first()
                if row is None:
                    data = _file_config_data()
                    new_id = conn.execute(insert(ConfigVersion).values(data=data, note="seed from config.yaml")
                                          .returning(ConfigVersion.id)).scalar_one()
                    row = (new_id, data)
        except SQLAlchemyError as exc:
            log.warning("config versions not readable (%s); using %s", exc,
                        "the last version read" if _active_config else "config.yaml")
            return (_active_config[1], _active_config[2]) if _active_config else None
        _active_config = (time.monotonic(), row[0], row[1])
        _config_by_id[row[0]] = row[1]
        return row[0], row[1]


def config_version(version_id: int) -> dict | None:
    if version_id not in _config_by_id:
        with require_engine().connect() as conn:
            data = conn.execute(select(ConfigVersion.data).where(ConfigVersion.id == version_id)).scalar_one_or_none()
        if data is None:
            return None
        _config_by_id[version_id] = data
    return _config_by_id[version_id]


def active_prompt_ids(market: str = "in") -> dict[str, int]:
    """{prompt name: newest version id} of one market; a prompt file in prompts/<market>/ with no version yet is
    seeded as its first version."""
    engine = get_engine()
    if engine is None:
        return {}
    with _lock:
        cached = _active_prompts.get(market)
        if cached and time.monotonic() - cached[0] < CHECK_EVERY_SEC:
            return cached[1]
        try:
            with engine.begin() as conn:
                newest = dict(conn.execute(select(PromptVersion.name, func.max(PromptVersion.id))
                                           .where(PromptVersion.market == market)
                                           .group_by(PromptVersion.name)).all())
                for name, text in _prompt_files(market).items():
                    if name not in newest:
                        newest[name] = conn.execute(insert(PromptVersion).values(
                            name=name, text=text, market=market, note=f"seed from prompts/{market}/")
                            .returning(PromptVersion.id)).scalar_one()
        except SQLAlchemyError as exc:
            log.warning("prompt versions not readable (%s)", exc)
            return cached[1] if cached else {}
        _active_prompts[market] = (time.monotonic(), newest)
        return newest


def prompt_text(version_id: int) -> str | None:
    if version_id not in _prompt_by_id:
        with require_engine().connect() as conn:
            text = conn.execute(select(PromptVersion.text).where(PromptVersion.id == version_id)).scalar_one_or_none()
        if text is None:
            return None
        _prompt_by_id[version_id] = text
    return _prompt_by_id[version_id]


# --- runs pinned to versions ---

def new_run_pins(market: str = "in") -> tuple[int | None, dict | None]:
    """(config version id, {prompt name: version id} of the run's market) for a run that starts now; (None, None)
    without a database. A run has one market, so its pins stay {name: id} as before stage M0."""
    active = active_config()
    return (active[0] if active else None), (dict(active_prompt_ids(market)) or None)


def _run_pin_row(run_id: str) -> tuple[int | None, dict | None, str]:
    if run_id not in _run_pins:
        engine = get_engine()
        if engine is None:
            return None, None, "in"
        try:
            with engine.connect() as conn:
                row = conn.execute(select(Run.config_version_id, Run.prompt_version_ids, Run.market)
                                   .where(Run.id == run_id)).first()
        except SQLAlchemyError as exc:
            log.warning("run versions not readable (%s)", exc)
            return None, None, "in"
        if len(_run_pins) > 500:
            _run_pins.clear()
        _run_pins[run_id] = ((row.config_version_id, row.prompt_version_ids, row.market or "in") if row
                             else (None, None, "in"))
    return _run_pins[run_id]


def pinned_ids(run_id: str) -> tuple[int | None, dict | None]:
    config_id, prompt_ids, _ = _run_pin_row(run_id)
    return config_id, prompt_ids


def run_market(run_id: str) -> str:
    """The run's market (stage M0); set when the run is created, never changed. "in" when unknown."""
    return _run_pin_row(run_id)[2]


def repin_run(run_id: str) -> None:
    """A new attempt on an old run (Resume, dev single-step re-run) uses the versions active now (of its market)."""
    market = run_market(run_id)
    config_id, prompt_ids = new_run_pins(market)
    engine = get_engine()
    if engine is None or config_id is None:
        return
    with engine.begin() as conn:
        conn.execute(update(Run).where(Run.id == run_id).values(config_version_id=config_id, prompt_version_ids=prompt_ids))
    _run_pins[run_id] = (config_id, prompt_ids, market)


def load_prompt(name: str) -> str:
    """Prompt text for the run this thread works on (its pinned version), else the newest version of the run's
    market, else the file prompts/<market>/<name>."""
    run_id = config_mod.current_run_id()
    market = run_market(run_id) if run_id else "in"
    version_id = (pinned_ids(run_id)[1] or {}).get(name) if run_id else None
    if version_id is None:
        version_id = active_prompt_ids(market).get(name)
    text = prompt_text(version_id) if version_id is not None else None
    return text if text is not None else (_prompts_dir(market) / name).read_text(encoding="utf-8")


# --- admin: config ---

def _who(conn, user_id: int | None) -> str | None:
    return conn.execute(select(User.email).where(User.id == user_id)).scalar_one_or_none() if user_id else None


def get_config_version(version_id: int | None = None) -> dict:
    """The newest (or one given) config version with who saved it."""
    active = active_config()
    if active is None:
        raise SettingsError([{"field": "config", "message": "no database"}])
    with require_engine().connect() as conn:
        row = conn.execute(select(ConfigVersion).where(ConfigVersion.id == (version_id or active[0]))).first()
        if row is None:
            raise SettingsError([{"field": "version", "message": "not found"}])
        return {"id": row.id, "active": row.id == active[0], "saved_at": row.created_at.isoformat(),
                "saved_by": _who(conn, row.created_by), "note": row.note, "data": row.data}


def list_config_versions(limit: int = 100) -> list[dict]:
    with require_engine().connect() as conn:
        rows = conn.execute(select(ConfigVersion.id, ConfigVersion.created_at, ConfigVersion.note, User.email)
                            .outerjoin(User, User.id == ConfigVersion.created_by)
                            .order_by(ConfigVersion.id.desc()).limit(limit)).all()
    return [{"id": r.id, "saved_at": r.created_at.isoformat(), "saved_by": r.email, "note": r.note} for r in rows]


def save_config(admin_id: int, data: Any, note: str | None, nodes: list[str], keep_origin: str | None = None,
                action: str = "save_config") -> int:
    """Check, then save as the next version (active for runs that start from now). paths stay as they are."""
    active = active_config()
    if isinstance(data, dict) and active:
        data = {**data, "paths": active[1].get("paths")}  # read-only: moving run folders under a live app loses runs
    checked, problems = check_config(data, nodes, keep_origin)
    if problems:
        raise SettingsError(problems)
    changed = sorted(k for k in checked if not active or checked[k] != active[1].get(k))
    with require_engine().begin() as conn:
        version_id = conn.execute(insert(ConfigVersion).values(data=checked, created_by=admin_id, note=note)
                                  .returning(ConfigVersion.id)).scalar_one()
        conn.execute(insert(AuditLog).values(admin_id=admin_id, action=action, target=f"config v{version_id}",
                                             details={"note": note, "changed": changed}))
    forget_cache()
    return version_id


def rollback_config(admin_id: int, version_id: int, nodes: list[str], keep_origin: str | None = None) -> int:
    data = config_version(version_id)
    if data is None:
        raise SettingsError([{"field": "version", "message": "not found"}])
    return save_config(admin_id, data, f"rollback to v{version_id}", nodes, keep_origin, action="rollback_config")


def import_config(admin_id: int, nodes: list[str], keep_origin: str | None = None) -> int:
    with open(config_mod.CONFIG_PATH, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return save_config(admin_id, data, "import from config.yaml", nodes, keep_origin, action="import_config")


# --- admin: prompts ---

def _prompt_target(market: str, name: str, number: int) -> str:
    """Audit target: "prompt verify.user.md v3" for India (as before stage M0), "prompt us/verify.user.md v1" for US."""
    return f"prompt {name} v{number}" if market == "in" else f"prompt {market}/{name} v{number}"


def list_prompts(market: str | None = None) -> list[dict]:
    """Active prompts of one market, or of every market when market is None (stage M0)."""
    out: list[dict] = []
    for m in ([market] if market else list(MARKETS)):
        ids = active_prompt_ids(m)
        if not ids:
            continue
        with require_engine().connect() as conn:
            counts = dict(conn.execute(select(PromptVersion.name, func.count()).where(PromptVersion.market == m)
                                       .group_by(PromptVersion.name)).all())
            rows = conn.execute(select(PromptVersion.id, PromptVersion.name, PromptVersion.created_at,
                                       PromptVersion.note, User.email)
                                .outerjoin(User, User.id == PromptVersion.created_by)
                                .where(PromptVersion.id.in_(list(ids.values()))).order_by(PromptVersion.name)).all()
        files = _prompt_files(m)
        # "number" = this prompt's own version number (1, 2, 3 ...); "id" = the row, used for rollback
        # file_differs (owner 28 Nov): prompts/<market>/<name> is not the active text, so "Import file" would change it
        out += [{"name": r.name, "market": m, "id": r.id, "number": counts[r.name],
                 "saved_at": r.created_at.isoformat(), "saved_by": r.email, "note": r.note,
                 "placeholders": sorted(FORMAT_FIELDS.get(r.name, [])),
                 "file_differs": r.name in files and not same_text(files[r.name], prompt_text(r.id))} for r in rows]
    return out


def same_text(a: str | None, b: str | None) -> bool:
    """Prompt texts equal apart from line endings (files on Windows have CRLF, the seed may not)."""
    return (a or "").replace("\r\n", "\n").strip() == (b or "").replace("\r\n", "\n").strip()


def get_prompt(name: str, version_id: int | None = None, market: str = "in") -> dict:
    ids = active_prompt_ids(market)
    if name not in ids:
        raise SettingsError([{"field": name, "message": "unknown prompt"}])
    with require_engine().connect() as conn:
        versions = conn.execute(select(PromptVersion.id, PromptVersion.created_at, PromptVersion.note, User.email)
                                .outerjoin(User, User.id == PromptVersion.created_by)
                                .where(PromptVersion.name == name, PromptVersion.market == market)
                                .order_by(PromptVersion.id.desc())).all()
    shown = version_id or ids[name]
    numbers = {v.id: len(versions) - i for i, v in enumerate(versions)}  # oldest = 1
    if shown not in numbers:
        raise SettingsError([{"field": "version", "message": "not found"}])
    return {"name": name, "market": market, "id": shown, "number": numbers[shown], "active": shown == ids[name],
            "text": prompt_text(shown), "placeholders": sorted(FORMAT_FIELDS.get(name, [])),
            "versions": [{"id": v.id, "number": numbers[v.id], "saved_at": v.created_at.isoformat(), "saved_by": v.email,
                          "note": v.note} for v in versions]}


def prompt_number(name: str, version_id: int, market: str = "in") -> int:
    """This prompt's own version number of a row (oldest = 1), counted within its market."""
    with require_engine().connect() as conn:
        return conn.execute(select(func.count()).select_from(PromptVersion)
                            .where(PromptVersion.name == name, PromptVersion.market == market,
                                   PromptVersion.id <= version_id)).scalar_one()


def save_prompt(admin_id: int, name: str, text: str, note: str | None, action: str = "save_prompt",
                market: str = "in") -> int:
    if name not in active_prompt_ids(market):
        raise SettingsError([{"field": name, "message": "unknown prompt"}])
    problems = check_prompt(name, text)
    if problems:
        raise SettingsError(problems)
    with require_engine().begin() as conn:
        version_id = conn.execute(insert(PromptVersion).values(name=name, text=text, market=market,
                                                               created_by=admin_id, note=note)
                                  .returning(PromptVersion.id)).scalar_one()
        number = conn.execute(select(func.count()).select_from(PromptVersion)
                              .where(PromptVersion.name == name, PromptVersion.market == market)).scalar_one()
        conn.execute(insert(AuditLog).values(admin_id=admin_id, action=action,
                                             target=_prompt_target(market, name, number),
                                             details={"note": note, "row": version_id, "market": market}))
    forget_cache()
    return version_id


def rollback_prompt(admin_id: int, name: str, version_id: int, market: str = "in") -> int:
    old = get_prompt(name, version_id, market)
    return save_prompt(admin_id, name, old["text"], f"rollback to v{old['number']}", action="rollback_prompt",
                       market=market)


def import_prompt(admin_id: int, name: str, market: str = "in") -> int:
    """The prompt's file as a new version — only when it differs from the active text (owner 28 Nov: a click with
    nothing new changes nothing). Returns the active version's row id (new or unchanged)."""
    return import_prompt_file(admin_id, name, market)["id"]


def import_prompt_file(admin_id: int, name: str, market: str = "in") -> dict:
    """{id, changed}: the file saved as a new version when it differs from the active text, else the active row."""
    files = _prompt_files(market)
    if name not in files:
        raise SettingsError([{"field": name, "message": f"no such file in prompts/{market}/"}])
    active = active_prompt_ids(market).get(name)
    if active is not None and same_text(files[name], prompt_text(active)):
        return {"id": active, "changed": False}
    new_id = save_prompt(admin_id, name, files[name], f"import from prompts/{market}/", action="import_prompt",
                         market=market)
    return {"id": new_id, "changed": True}


def import_all_prompts(admin_id: int, market: str | None = None) -> list[dict]:
    """Owner 28 Nov: every file in prompts/<market>/ (every market when None) imported in one go — only files that
    differ from their active version get a new version. A file with no version yet is seeded first (as on listing).
    Returns one line per file: {market, name, changed, from, to} (version numbers)."""
    out = []
    for m in ([market] if market else list(MARKETS)):
        ids = active_prompt_ids(m)  # seeds files that have no version yet
        for name in sorted(_prompt_files(m)):
            before = prompt_number(name, ids[name], m) if name in ids else None
            result = import_prompt_file(admin_id, name, m)
            out.append({"market": m, "name": name, "changed": result["changed"], "from": before,
                        "to": prompt_number(name, result["id"], m)})
    return out
