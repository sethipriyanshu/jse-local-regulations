"""Admin view gate for the MVP: one shared passcode, exchanged for a signed cookie.

This is a stand-in until Entra ID login is added (PLAN.md D4/H5). It only
separates the admin view from the user view.
"""

import hashlib
import hmac
import time
from collections import defaultdict, deque
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel

from app.config import Settings, get_settings

COOKIE = "jse_admin"
TTL_SECONDS = 12 * 60 * 60
MAX_ATTEMPTS_PER_MINUTE = 5

router = APIRouter(prefix="/admin", tags=["admin"])
_attempts: dict[str, deque[float]] = defaultdict(deque)


def _sign(expires: int, secret: str) -> str:
    mac = hmac.new(secret.encode(), str(expires).encode(), hashlib.sha256).hexdigest()
    return f"{expires}.{mac}"


def _valid(token: str | None, secret: str) -> bool:
    if not token or "." not in token:
        return False
    expires_s, _ = token.split(".", 1)
    if not expires_s.isdigit() or int(expires_s) < time.time():
        return False
    return hmac.compare_digest(token, _sign(int(expires_s), secret))


def is_admin(
    settings: Annotated[Settings, Depends(get_settings)],
    jse_admin: Annotated[str | None, Cookie()] = None,
) -> bool:
    return _valid(jse_admin, settings.session_secret)


def require_admin(admin: Annotated[bool, Depends(is_admin)]) -> None:
    """Dependency for admin-only endpoints."""
    if not admin:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Admin passcode required")


class LoginBody(BaseModel):
    passcode: str


@router.get("/session")
def session(admin: Annotated[bool, Depends(is_admin)]) -> dict[str, bool]:
    return {"admin": admin}


@router.post("/login")
def login(
    body: LoginBody,
    request: Request,
    response: Response,
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, bool]:
    client = request.client.host if request.client else "unknown"
    now = time.time()
    window = _attempts[client]
    while window and window[0] < now - 60:
        window.popleft()
    if len(window) >= MAX_ATTEMPTS_PER_MINUTE:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many attempts, wait a minute")
    window.append(now)

    if not hmac.compare_digest(body.passcode.encode(), settings.admin_passcode.encode()):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong passcode")

    expires = int(now) + TTL_SECONDS
    response.set_cookie(
        COOKIE,
        _sign(expires, settings.session_secret),
        max_age=TTL_SECONDS,
        httponly=True,
        samesite="strict",
        secure=settings.env != "local",
    )
    return {"admin": True}


@router.post("/logout")
def logout(response: Response) -> dict[str, bool]:
    response.delete_cookie(COOKIE)
    return {"admin": False}
