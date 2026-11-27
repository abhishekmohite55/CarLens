from __future__ import annotations

import logging
import threading
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
from threading import Lock
from typing import Optional

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .market import MARKETS, move_market_keys

PROJECT_ROOT = Path(__file__).parent.parent.parent  # F:\CarLens

load_dotenv(dotenv_path=PROJECT_ROOT / ".env")

_CONFIG_PATH = CONFIG_PATH = PROJECT_ROOT / "config.yaml"
_lock = Lock()
_mtime: float = -1.0
_config: Optional["AppConfig"] = None
_last_valid: Optional["AppConfig"] = None


class ModelEntry(BaseModel):
    provider: str
    model: str
    fallback_model: Optional[str] = None
    timeout_sec: Optional[int] = None  # this model only; empty = the chain's timeout (step 6.3)
    temperature: Optional[float] = None  # this model only; empty = models.temperature


class UploadConfig(BaseModel):
    allowed_types: list[str]
    max_size_mb: int
    max_duration_sec: int
    pending_minutes: int = 30  # same video again: the kept upload waits this long for the user's choice (step 5)
    max_parallel: int = Field(2, ge=1)  # hardening A2: uploads received and checked at once (users)
    repeat_warn_count: int = Field(3, ge=1)  # hardening A2: same-video / refused uploads that flag a user in admin
    repeat_window_min: int = Field(60, ge=1)  # ... counted over this many minutes


class ModelsConfig(BaseModel):
    locate: ModelEntry
    verify_chain: list[ModelEntry]
    plan_chain: list[ModelEntry]
    plan_timeout_per_model_sec: int = 120
    extract_chain: list[ModelEntry]
    extract_timeout_per_model_sec: int = 120
    extract_reasoning_effort: Optional[str] = None
    temperature: float
    timeout_sec: int
    locate_media_resolution: str
    verify_media_resolution: str = "medium"
    verify_thinking_level: Optional[str] = None
    verify_timeout_per_model_sec: int = 180
    locate_thinking_level: Optional[str] = None
    photos_chain: list[ModelEntry] = []  # empty = use verify_chain
    photos_timeout_per_model_sec: int = 180
    max_calls_in_flight: int = Field(6, ge=1)  # hardening A3: model calls still running (also timed-out ones) at most


class LocateVideoConfig(BaseModel):
    shrink: bool
    height: int
    fps: int
    crf: int
    shrink_timeout_sec: int = Field(600, ge=30)  # hardening A4: longer = ffmpeg stopped, locate fails (no Gemini call)


class FramesConfig(BaseModel):
    window_sec: float
    sample_fps: int
    score_scale: float
    workers: int
    max_long_edge_px: int
    jpeg_quality: int
    extra_frames_for: list[str] = ["damage"]  # owner 27 Nov: these categories also get locate's frame + another angle
    extra_min_gap_sec: float = Field(0.5, ge=0)  # "another angle" is at least this far from the other frames


class ConfirmConfig(BaseModel):
    expand_below_confidence: float
    year_range: int = 8


class PhotosConfig(BaseModel):
    allowed_types: list[str] = ["jpg", "jpeg", "png", "webp", "heic"]
    max_size_mb: int = 10
    km_min_confidence: float = 0.8
    max_pixels: int = Field(50_000_000, ge=1_000_000)  # hardening A4: larger photos refused before decoding
    max_parallel: int = Field(2, ge=1)  # hardening A4: photos decoded at once


class PlanConfig(BaseModel):
    queries_per_part: int
    listing_queries_per_run: int
    tyre_ok_score: int
    new_price_queries_per_run: int = 2
    # listing_templates / new_price_templates: per market, markets.<market> (stage M0)


class SearchConfig(BaseModel):
    depth: str
    max_results: int
    include_raw_content: bool
    include_domains: list[str]
    exclude_domains: list[str] = []
    workers: int  # country: per market, markets.<market>.search_country (stage M0)


class ExtractConfig(BaseModel):
    max_results_per_group: int
    max_snippet_chars: int
    outlier_factor: float  # listing limits: per market, markets.<market>.extract_limits (stage M0)


class PricingConfig(BaseModel):
    year_tolerance: int
    min_comparables: int  # tyre deduction: per market, markets.<market>.tyre_minor_wear_deduction (stage M0)
    min_listings_with_year: int = 3
    max_from_top: int = 3
    min_listing_age: int = 2


class PathsConfig(BaseModel):
    runs_dir: str
    prompts_dir: str


class DevConfig(BaseModel):
    stop_after: Optional[str] = None  # India: node name, the pipeline ends after it (platform step 2 testing); empty = all
    stop_after_us: Optional[str] = None  # US (stage M0): "upload" (upload/vin: locate never starts) or a node; empty = all
    markets_on: dict[str, bool] = {"in": True, "us": False}  # off = no new runs / resumes / re-runs in that market


class ExtractLimits(BaseModel):
    listing_min: int  # car prices (listing / new price) below this are dropped (the market's currency)
    listing_max: int  # ... and above this


class MarketConfig(BaseModel):
    """Settings that differ per market (stage M0, docs/backend/07-us-market.md §9)."""
    currency: str
    distance_unit: str
    search_country: Optional[str] = None  # Tavily boosts results from this country
    listing_templates: list[str] = []
    new_price_templates: list[str] = []
    extract_limits: ExtractLimits
    tyre_minor_wear_deduction: int


class UsMarketConfig(MarketConfig):
    currency: str = "USD"
    distance_unit: str = "mi"
    search_country: Optional[str] = "united states"
    extract_limits: ExtractLimits = ExtractLimits(listing_min=1000, listing_max=300000)
    tyre_minor_wear_deduction: int = 50
    top_states: list[str] = ["CA", "TX", "FL", "NY", "PA", "IL", "OH", "GA", "NC"]
    state_templates_max: int = Field(2, ge=0)
    odometer_min_confidence: float = Field(0.8, ge=0, le=1)
    vin_mismatch_action: str = "stop"  # owner 27 Nov: video not the VIN's car → stop after verify, or warn and go on
    vin_mismatch_min_confidence: float = Field(0.8, ge=0, le=1)  # only a mismatch this sure counts
    miles_min: int = Field(1, ge=0)  # stage U2: miles the user may type at upload
    miles_max: int = Field(999_999, ge=1)


class MarketsConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)  # "in" is a Python keyword

    default: str = "in"
    country_map: dict[str, str] = {"US": "us"}
    in_: MarketConfig = Field(alias="in", serialization_alias="in")
    us: UsMarketConfig = UsMarketConfig()

    def of(self, market: str) -> MarketConfig:
        return self.us if market == "us" else self.in_


class AuthConfig(BaseModel):
    """Sign-in (platform step 5, docs/platform/05-login.md)."""
    session_hours: int = 24
    max_failed_logins: int = 4
    lockout_minutes: int = 15
    max_signups_per_hour: int = 5
    cookie_secure: bool = False  # true on AWS (https only)
    allowed_origins: list[str] = ["http://127.0.0.1:8000", "http://localhost:8000", "http://localhost:5173"]
    client_ip_header: str = ""  # step 8.2: "X-Viewer-IP" on AWS (set by a CloudFront Function); empty = direct address


class AccessConfig(BaseModel):
    """Access requests (platform step 5/6)."""
    default_tokens: int = 5  # given when the owner approves a request
    free_resumes_per_run: int = Field(2, ge=0)  # hardening A7: a user may resume while failures <= this
    max_active_runs: int = Field(2, ge=1)  # hardening A7: runs uploaded or working at once (all users)
    max_event_streams: int = Field(50, ge=1)  # hardening A7: live run pages open at once (all users)


class MaintenanceConfig(BaseModel):
    """Maintenance mode during a deploy (platform step 9, docs/platform/09-cd.md §5a)."""
    confirm_grace_min: int = Field(5, ge=0)  # runs waiting at confirm may still be confirmed this long
    max_wait_min: int = Field(30, ge=1)  # the deploy waits at most this long for working runs
    stale_confirm_min: int = Field(15, ge=1)  # a run at confirm longer than this does not hold a deploy back
    auto_off_min: int = Field(60, ge=5)  # step 9.3 safety net: maintenance on longer than this counts as off


class StorageConfig(BaseModel):
    """Run files on S3 (platform step 8.1); used only when the env var S3_BUCKET is set."""
    local_keep_days: int = Field(7, ge=1)  # finished runs untouched this long lose their server copy (S3 keeps it)


VPIC_FIELDS = {"make": "Make", "model": "Model", "year": "ModelYear", "trim": "Trim", "series": "Series",
               "fuel": "FuelTypePrimary", "body": "BodyClass", "displacement_l": "DisplacementL",
               "cylinders": "EngineCylinders", "engine_layout": "EngineConfiguration", "drive": "DriveType"}


class VinProviderConfig(BaseModel):
    base_url: str
    timeout_sec: float = Field(10, gt=0)
    key_env: str = ""  # name of the .env variable with the key; empty = no key (vPIC)
    fields: dict[str, str] = {}  # common name → the provider's key (or dotted path)


class VinConfig(BaseModel):
    """VIN lookup (stage U1, docs/backend/07-us-market.md §4): the provider and how to read it."""
    provider: str = "vpic"
    cache_days: int = Field(30, ge=0)  # same VIN within this many days → the saved answer, no second call
    max_lookups_per_hour: int = Field(20, ge=1)  # real provider calls per user (the admin has no limit)
    providers: dict[str, VinProviderConfig] = {
        "vpic": VinProviderConfig(base_url="https://vpic.nhtsa.dot.gov/api/vehicles", fields=VPIC_FIELDS)}


class AppConfig(BaseModel):
    model_config = ConfigDict(serialize_by_alias=True)  # stage M0: markets.in is saved as "in", not "in_"

    upload: UploadConfig
    models: ModelsConfig
    frames: FramesConfig
    confirm: ConfirmConfig
    photos: PhotosConfig = PhotosConfig()
    plan: PlanConfig
    search: SearchConfig
    extract: ExtractConfig
    pricing: PricingConfig
    paths: PathsConfig
    locate_video: LocateVideoConfig
    dev: DevConfig = DevConfig()
    auth: AuthConfig = AuthConfig()
    access: AccessConfig = AccessConfig()
    storage: StorageConfig = StorageConfig()
    maintenance: MaintenanceConfig = MaintenanceConfig()
    markets: MarketsConfig
    vin: VinConfig = VinConfig()

    @model_validator(mode="before")
    @classmethod
    def _old_market_keys(cls, data):
        """Config versions saved before stage M0 keep loading: their India keys move under markets.in."""
        return move_market_keys(data)


# --- which config a caller gets (platform step 6.3, docs/platform/06-admin.md §6.1) ---
# From step 6.3 the config lives in the database (settings_store): the newest version is active, and a run is
# pinned to the version active when it started. config.yaml is the seed and the fallback without a database.

_pin = threading.local()
_parsed: dict[int, AppConfig] = {}


@contextmanager
def pinned_run(run_id: str | None):
    """Inside this block, get_config() on this thread returns the config version pinned on the run."""
    previous = getattr(_pin, "run_id", None)
    _pin.run_id = run_id
    try:
        yield
    finally:
        _pin.run_id = previous


def pinned(fn):
    """Decorator for node entry points fn(run_id, ...): the node works with its run's config and prompts."""
    @wraps(fn)
    def wrapper(run_id, *args, **kwargs):
        with pinned_run(run_id):
            return fn(run_id, *args, **kwargs)
    return wrapper


def current_run_id() -> str | None:
    return getattr(_pin, "run_id", None)


def current_market() -> str:
    """Market of the run this thread works on (stage M0); "in" outside a run (the behaviour before markets)."""
    from . import settings_store  # imported here: settings_store imports this module

    run_id = current_run_id()
    market = settings_store.run_market(run_id) if run_id else None
    return market if market in MARKETS else "in"


def market_config(market: str | None = None) -> MarketConfig:
    """markets.<market> of the config in use; the run's own market when none is given."""
    return get_config().markets.of(market or current_market())


def _from_version(version_id: int, data: dict) -> AppConfig:
    if version_id not in _parsed:
        if len(_parsed) > 50:
            _parsed.clear()
        _parsed[version_id] = AppConfig(**data)
    return _parsed[version_id]


def get_config() -> AppConfig:
    """The config for this thread's pinned run, else the newest version, else config.yaml (no database)."""
    from . import settings_store  # imported here: settings_store imports this module

    run_id = current_run_id()
    if run_id:
        version_id = settings_store.pinned_ids(run_id)[0]
        data = settings_store.config_version(version_id) if version_id else None
        if data is not None:
            return _from_version(version_id, data)
    active = settings_store.active_config()
    if active is None:
        return file_config()
    try:
        return _from_version(*active)
    except Exception as exc:  # a stored version this code can no longer read
        logging.warning("config version %s not usable (%s); using config.yaml", active[0], exc)
        return file_config()


def file_config() -> AppConfig:
    """config.yaml, re-read when the file changes."""
    global _mtime, _config, _last_valid
    with _lock:
        try:
            mtime = _CONFIG_PATH.stat().st_mtime
        except OSError as exc:
            logging.error("Cannot stat config.yaml: %s", exc)
            if _last_valid:
                return _last_valid
            raise

        if _config is not None and mtime == _mtime:
            return _config

        try:
            with open(_CONFIG_PATH, encoding="utf-8") as f:
                data = yaml.safe_load(f)
            new_cfg = AppConfig(**data)
            _config = new_cfg
            _mtime = mtime
            _last_valid = new_cfg
            return new_cfg
        except Exception as exc:
            logging.warning("config.yaml reload failed (%s); keeping last valid config", exc)
            if _last_valid:
                return _last_valid
            raise
