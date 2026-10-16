"""Admin login and the configuration entered in the UI.

Without an admin login (CXS_ADMIN_PASSWORD_HASH and CXS_SECRET_KEY unset) the app behaves as
before: partners are editable by anyone and the configuration only through the deployment.
"""

from __future__ import annotations

import logging
import re
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from ..admin import FIELDS, AdminAuth, locked
from ..admin.config_store import BY_KEY
from .schemas import ConnectionCheckOut, UtcDatetime

log = logging.getLogger(__name__)

COOKIE = "cxs_admin"
URL = re.compile(r"^https?://\S+$")

router = APIRouter(prefix="/api")


def _auth(request: Request) -> AdminAuth | None:
    return request.app.state.admin


def current_admin(request: Request) -> str | None:
    auth = _auth(request)
    return auth.user(request.cookies.get(COOKIE)) if auth else None


def require_admin(request: Request) -> str:
    """An admin session; configuration changes always need one."""
    if _auth(request) is None:
        raise HTTPException(
            status_code=503,
            detail="admin login is not set up (CXS_ADMIN_PASSWORD_HASH and CXS_SECRET_KEY)",
        )
    user = current_admin(request)
    if user is None:
        raise HTTPException(status_code=401, detail="sign in as admin")
    return user


def admin_if_enabled(request: Request) -> str | None:
    """An admin session if the admin login is set up; otherwise anyone (as before)."""
    return require_admin(request) if _auth(request) is not None else None


Admin = Annotated[str, Depends(require_admin)]


class LoginIn(BaseModel):
    username: str = Field(max_length=64)
    password: str = Field(max_length=256)


class MeOut(BaseModel):
    login_enabled: bool
    admin: str | None
    # An admin can enter settings in the UI (needs CXS_SECRET_KEY).
    config_editable: bool


def _me(request: Request) -> MeOut:
    return MeOut(
        login_enabled=_auth(request) is not None,
        admin=current_admin(request),
        config_editable=_auth(request) is not None and request.app.state.runtime.store.available,
    )


@router.get("/auth/me", response_model=MeOut)
def me(request: Request) -> MeOut:
    return _me(request)


@router.post("/auth/login", response_model=MeOut)
async def login(body: LoginIn, request: Request, response: Response) -> MeOut:
    auth = _auth(request)
    if auth is None:
        raise HTTPException(status_code=503, detail="admin login is not set up")
    client = request.client.host if request.client else "unknown"
    if auth.locked_out(client):
        raise HTTPException(status_code=429, detail="too many failed sign-ins, try again later")
    token = await run_in_threadpool(auth.login, client, body.username, body.password)
    if token is None:
        log.warning("failed admin sign-in from %s", client)
        raise HTTPException(status_code=401, detail="wrong username or password")
    log.info("admin %s signed in from %s", auth.username, client)
    response.set_cookie(
        COOKIE,
        token,
        max_age=request.app.state.settings.admin_session_hours * 3600,
        httponly=True,
        samesite="strict",
        secure=request.url.scheme == "https",
        path="/",
    )
    return MeOut(
        login_enabled=True, admin=auth.username, config_editable=_me(request).config_editable
    )


@router.post("/auth/logout", response_model=MeOut)
def logout(request: Request, response: Response) -> MeOut:
    response.delete_cookie(COOKIE, path="/")
    return MeOut(login_enabled=_auth(request) is not None, admin=None, config_editable=False)


class ConfigFieldOut(BaseModel):
    key: str
    variable: str  # the environment variable of the deployment
    group: str  # registry | connector | notifications | services
    label: str
    hint: str
    secret: bool
    url: bool
    # deploy: set by the deployment (locked); app: entered here; None: not set
    source: str | None
    locked: bool
    # The effective value; never returned for secrets.
    value: str | None
    is_set: bool
    # A stored secret that the current CXS_SECRET_KEY cannot decrypt.
    unreadable: bool = False
    updated_at: UtcDatetime | None = None
    updated_by: str | None = None


class ConfigUpdate(BaseModel):
    # A new value, or null / "" to remove what was entered here. Secrets left out stay as they are.
    values: dict[str, str | None]


class ConfigSaved(BaseModel):
    fields: list[ConfigFieldOut]
    checks: list[ConnectionCheckOut]


def _fields(request: Request) -> list[ConfigFieldOut]:
    runtime = request.app.state.runtime
    base = runtime.base
    settings = request.app.state.settings
    rows = runtime.store.rows() if runtime.store.available else {}
    _, unreadable = runtime.store.values()
    out = []
    for field in FIELDS:
        is_locked = locked(base, field)
        row = rows.get(field.key)
        value = getattr(settings, field.key)
        source = "deploy" if is_locked else ("app" if row is not None else None)
        out.append(
            ConfigFieldOut(
                key=field.key,
                variable=field.variable,
                group=field.group,
                label=field.label,
                hint=field.hint,
                secret=field.secret,
                url=field.url,
                source=source,
                locked=is_locked,
                value=None if field.secret else value,
                is_set=bool(value),
                unreadable=field.key in unreadable and not is_locked,
                updated_at=row.updated_at if row is not None and not is_locked else None,
                updated_by=row.updated_by if row is not None and not is_locked else None,
            )
        )
    return out


@router.get("/setup/config", response_model=list[ConfigFieldOut])
def get_config(request: Request, _: Admin) -> list[ConfigFieldOut]:
    return _fields(request)


def _validated(update: ConfigUpdate, request: Request) -> dict[str, str | None]:
    base = request.app.state.runtime.base
    changes: dict[str, str | None] = {}
    errors: list[str] = []
    for key, raw in update.values.items():
        field = BY_KEY.get(key)
        if field is None:
            errors.append(f"{key}: not a setting that can be entered here")
            continue
        if locked(base, field):
            errors.append(f"{field.label}: set by the deployment ({field.variable})")
            continue
        value = (raw or "").strip() or None
        if value is not None:
            if len(value) > 2048:
                errors.append(f"{field.label}: too long")
            elif field.url and not URL.match(value):
                errors.append(f"{field.label}: must start with http:// or https://")
        changes[key] = value
    if errors:
        raise HTTPException(status_code=422, detail="; ".join(errors))
    return changes


@router.put("/setup/config", response_model=ConfigSaved)
async def put_config(update: ConfigUpdate, request: Request, user: Admin) -> ConfigSaved:
    """Store the settings, rebuild the connections with them and test them."""
    runtime = request.app.state.runtime
    if not runtime.store.available:
        raise HTTPException(status_code=503, detail="CXS_SECRET_KEY is not set")
    changes = _validated(update, request)
    await run_in_threadpool(runtime.store.save, changes, user)
    # Keys only: the values (and secrets) stay out of the log.
    log.info("configuration changed by %s: %s", user, ", ".join(sorted(changes)) or "nothing")
    await runtime.reload()
    checks = await run_in_threadpool(request.app.state.connection_tester.run)
    return ConfigSaved(
        fields=_fields(request),
        checks=[ConnectionCheckOut.model_validate(c) for c in checks],
    )
