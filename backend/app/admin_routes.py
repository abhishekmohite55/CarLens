"""/api/admin/* (platform step 6, docs/platform/06-admin.md §6). Admin only; every change is audited."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from . import admin_data
from .auth import SignedIn, require_admin
from .graph import forget_run
from .runs import run_dir

router = APIRouter(prefix="/api/admin")


class TokensBody(BaseModel):
    set: int | None = None  # exact number
    add: int | None = None  # or a change (negative removes)


class PasswordBody(BaseModel):
    password: str


@router.get("/users")
def users(status: str | None = None, admin: SignedIn = Depends(require_admin)):
    return {"users": admin_data.list_users(status)}


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
def runs(status: str | None = None, admin: SignedIn = Depends(require_admin)):
    return {"runs": admin_data.list_runs(status)}


@router.get("/runs/{run_id}")
def run_detail(run_id: str, admin: SignedIn = Depends(require_admin)):
    return {"run_id": run_id, "steps": admin_data.run_steps(run_id)}


@router.post("/runs/{run_id}/fail")
def fail_run(run_id: str, admin: SignedIn = Depends(require_admin)):
    admin_data.mark_run_failed(admin.id, run_id)
    return {"ok": True}


@router.delete("/runs/{run_id}")
def remove_run(run_id: str, admin: SignedIn = Depends(require_admin)):
    admin_data.delete_run(admin.id, run_id, run_dir(run_id), forget_run)
    return {"ok": True}


@router.get("/audit")
def audit(action: str | None = None, admin: SignedIn = Depends(require_admin)):
    return {"entries": admin_data.list_audit(action)}
