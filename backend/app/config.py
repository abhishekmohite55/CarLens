from __future__ import annotations

import logging
from pathlib import Path
from threading import Lock
from typing import Optional

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel

PROJECT_ROOT = Path(__file__).parent.parent.parent  # F:\CarLens

load_dotenv(dotenv_path=PROJECT_ROOT / ".env")

_CONFIG_PATH = PROJECT_ROOT / "config.yaml"
_lock = Lock()
_mtime: float = -1.0
_config: Optional["AppConfig"] = None
_last_valid: Optional["AppConfig"] = None


class ModelEntry(BaseModel):
    provider: str
    model: str
    fallback_model: Optional[str] = None


class UploadConfig(BaseModel):
    allowed_types: list[str]
    max_size_mb: int
    max_duration_sec: int


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


class LocateVideoConfig(BaseModel):
    shrink: bool
    height: int
    fps: int
    crf: int


class FramesConfig(BaseModel):
    window_sec: float
    sample_fps: int
    score_scale: float
    workers: int
    max_long_edge_px: int
    jpeg_quality: int


class ConfirmConfig(BaseModel):
    expand_below_confidence: float
    year_range: int = 8


class PhotosConfig(BaseModel):
    allowed_types: list[str] = ["jpg", "jpeg", "png", "webp"]
    max_size_mb: int = 10
    km_min_confidence: float = 0.8


class PlanConfig(BaseModel):
    queries_per_part: int
    listing_queries_per_run: int
    tyre_ok_score: int
    listing_templates: list[str]
    new_price_queries_per_run: int = 2
    new_price_templates: list[str] = []


class SearchConfig(BaseModel):
    depth: str
    max_results: int
    include_raw_content: bool
    include_domains: list[str]
    exclude_domains: list[str] = []
    country: Optional[str] = None
    workers: int


class ExtractConfig(BaseModel):
    max_results_per_group: int
    max_snippet_chars: int
    listing_min_inr: int
    listing_max_inr: int
    outlier_factor: float


class PricingConfig(BaseModel):
    year_tolerance: int
    min_comparables: int
    tyre_minor_wear_deduction_inr: int
    min_listings_with_year: int = 3
    max_from_top: int = 3
    min_listing_age: int = 2


class PathsConfig(BaseModel):
    runs_dir: str
    prompts_dir: str
    rto_csv: str = "rto_codes.csv"


class AppConfig(BaseModel):
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


def get_config() -> AppConfig:
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
