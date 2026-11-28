"""/api/admin/* (platform step 6, docs/platform/06-admin.md §6). Admin only; every change is audited."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from . import admin_data, health, settings_store
from .auth import SignedIn, require_admin
from .config import get_config
from .graph import ORDER, forget_run
from .market import MARKETS, US_NODES, checked_market
from .run_index import is_run_id
from .runs import run_dir

router = APIRouter(prefix="/api/admin")


class TokensBody(BaseModel):
    set: int | None = None  # exact number
    add: int | None = None  # or a change (negative removes)


class PasswordBody(BaseModel):
    password: str


class MarketBody(BaseModel):
    market: str | None = None  # in / us; empty = by location


def _one_market(market: str | None) -> str:
    """Prompt routes work on one market's prompts: in (default, as before stage M0) or us."""
    if market in (None, ""):
        return "in"
    if market not in MARKETS:
        raise HTTPException(400, detail=f"market must be one of {', '.join(MARKETS)}")
    return market


# Stage M0: every list takes ?market=all|in|us (the admin header switch); empty / all = every market.

@router.get("/users")
def users(status: str | None = None, market: str | None = None, admin: SignedIn = Depends(require_admin)):
    return {"users": admin_data.list_users(status, checked_market(market))}


@router.patch("/users/{user_id}/market")
def user_market(user_id: int, body: MarketBody, admin: SignedIn = Depends(require_admin)):
    admin_data.set_market(admin.id, user_id, body.market or None)
    return {"market": body.market or None}


@router.post("/users/{user_id}/approve")
def approve(user_id: int, admin: SignedIn = Depends(require_admin)):
    admin_data.approve_user(admin.id, user_id)
    return {"ok": True}


@router.post("/users/{user_id}/reject")
def reject(user_id: int, admin: SignedIn = Depends(require_admin)):
    admin_data.reject_user(admin.id, user_id)
    return {"ok": True}


@router.patch("/users/{user_id}/tokens")
def tokens(user_id: int, body: TokensBody, admin: SignedIn = Depends(require_admin)):
    return {"tokens": admin_data.change_tokens(admin.id, user_id, body.set, body.add)}


@router.post("/users/{user_id}/password")
def password(user_id: int, body: PasswordBody, admin: SignedIn = Depends(require_admin)):
    admin_data.reset_password(admin.id, user_id, body.password)
    return {"ok": True}


@router.post("/users/{user_id}/signout")
def signout(user_id: int, admin: SignedIn = Depends(require_admin)):
    admin_data.sign_out_user(admin.id, user_id)
    return {"ok": True}


@router.delete("/users/{user_id}")
def remove_user(user_id: int, admin: SignedIn = Depends(require_admin)):
    admin_data.delete_user(admin.id, user_id)
    return {"ok": True}


@router.get("/runs")
def runs(status: str | None = None, market: str | None = None, admin: SignedIn = Depends(require_admin)):
    return {"runs": admin_data.list_runs(status, market=checked_market(market))}


def _checked_run_id(run_id: str) -> str:
    """Hardening S14: only real run ids reach the database, the run folder and S3."""
    if not is_run_id(run_id):
        raise HTTPException(404, detail="Run not found.")
    return run_id


@router.get("/runs/{run_id}")
def run_detail(run_id: str = Depends(_checked_run_id), admin: SignedIn = Depends(require_admin)):
    return {"run_id": run_id, "steps": admin_data.run_steps(run_id)}


@router.post("/runs/{run_id}/fail")
def fail_run(run_id: str = Depends(_checked_run_id), admin: SignedIn = Depends(require_admin)):
    admin_data.mark_run_failed(admin.id, run_id)
    return {"ok": True}


@router.delete("/runs/{run_id}")
def remove_run(run_id: str = Depends(_checked_run_id), admin: SignedIn = Depends(require_admin)):
    admin_data.delete_run(admin.id, run_id, run_dir(run_id), forget_run)
    return {"ok": True}


@router.get("/audit")
def audit(action: str | None = None, market: str | None = None, admin: SignedIn = Depends(require_admin)):
    return {"entries": admin_data.list_audit(action, market=checked_market(market))}


# --- config and prompts (stage 6.3): versions in the database; a save applies to runs that start from now ---

class ConfigBody(BaseModel):
    data: dict[str, Any]
    note: str | None = None


class PromptBody(BaseModel):
    text: str
    note: str | None = None


def _origin(request: Request) -> str | None:
    return request.headers.get("origin")


@router.get("/config")
def config(admin: SignedIn = Depends(require_admin)):
    return {**settings_store.get_config_version(),
            "options": {"stop_after": ORDER, "stop_after_us": list(US_NODES), "markets": list(MARKETS),
                        "providers": list(settings_store.PROVIDERS)}}


@router.get("/config/versions")
def config_versions(admin: SignedIn = Depends(require_admin)):
    return {"versions": settings_store.list_config_versions()}


@router.get("/config/versions/{version_id}")
def config_version(version_id: int, admin: SignedIn = Depends(require_admin)):
    return settings_store.get_config_version(version_id)


@router.put("/config")
def save_config(body: ConfigBody, request: Request, admin: SignedIn = Depends(require_admin)):
    return {"version": settings_store.save_config(admin.id, body.data, body.note, ORDER, _origin(request))}


@router.post("/config/rollback/{version_id}")
def rollback_config(version_id: int, request: Request, admin: SignedIn = Depends(require_admin)):
    return {"version": settings_store.rollback_config(admin.id, version_id, ORDER, _origin(request))}


@router.post("/config/import")
def import_config(request: Request, admin: SignedIn = Depends(require_admin)):
    return {"version": settings_store.import_config(admin.id, ORDER, _origin(request))}


@router.get("/prompts")
def prompts(market: str | None = None, admin: SignedIn = Depends(require_admin)):
    return {"prompts": settings_store.list_prompts(checked_market(market))}


@router.post("/prompts/import-all")
def import_all_prompts(market: str | None = None, admin: SignedIn = Depends(require_admin)):
    """Owner 28 Nov: every prompt file of the market (or all markets); only changed files get a new version."""
    results = settings_store.import_all_prompts(admin.id, checked_market(market))
    return {"results": results, "changed": sum(1 for r in results if r["changed"])}


@router.get("/prompts/{name}")
def prompt(name: str, version: int | None = None, market: str | None = None,
           admin: SignedIn = Depends(require_admin)):
    return settings_store.get_prompt(name, version, _one_market(market))


@router.put("/prompts/{name}")
def save_prompt(name: str, body: PromptBody, market: str | None = None, admin: SignedIn = Depends(require_admin)):
    m = _one_market(market)
    version_id = settings_store.save_prompt(admin.id, name, body.text, body.note, market=m)
    return {"version": settings_store.prompt_number(name, version_id, m)}


@router.post("/prompts/{name}/rollback/{version_id}")
def rollback_prompt(name: str, version_id: int, market: str | None = None,
                    admin: SignedIn = Depends(require_admin)):
    m = _one_market(market)
    new_id = settings_store.rollback_prompt(admin.id, name, version_id, m)
    return {"version": settings_store.prompt_number(name, new_id, m)}


@router.post("/prompts/{name}/import")
def import_prompt(name: str, market: str | None = None, admin: SignedIn = Depends(require_admin)):
    m = _one_market(market)
    result = settings_store.import_prompt_file(admin.id, name, m)  # owner 28 Nov: no new version when unchanged
    return {"version": settings_store.prompt_number(name, result["id"], m), "changed": result["changed"]}


# --- dashboard and tables (stage 6.4) ---

@router.get("/health")
def admin_health(admin: SignedIn = Depends(require_admin)):
    """Step 9.3: every problem in plain words (red banner in the admin app)."""
    return health.check(detail=True)


@router.get("/dashboard")
def dashboard(days: int = 30, market: str | None = None, admin: SignedIn = Depends(require_admin)):
    up = get_config().upload
    return admin_data.dashboard(days, up.repeat_window_min, up.repeat_warn_count, checked_market(market))


@router.get("/tables")
def tables(market: str | None = None, admin: SignedIn = Depends(require_admin)):
    return {"tables": admin_data.list_tables(checked_market(market))}


@router.get("/tables/{name}")
def table(name: str, page: int = 1, sort: str | None = None, desc: bool = True, search: str | None = None,
          column: str | None = None, value: str | None = None, market: str | None = None,
          admin: SignedIn = Depends(require_admin)):
    return admin_data.table_rows(name, page, sort, desc, search, column, value, checked_market(market))
