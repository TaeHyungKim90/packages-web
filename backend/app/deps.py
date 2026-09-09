from typing import Annotated

from fastapi import Depends, HTTPException, Request, Response

from app.config import settings
from app.services import github
from app.services.session import SessionUser, dump_session, load_session


def set_session_cookie(response: Response, user: SessionUser) -> None:
    response.set_cookie(
        key=settings.session_cookie_name,
        value=dump_session(user),
        max_age=settings.session_max_age_seconds,
        httponly=True,
        samesite="lax",
        secure=settings.session_cookie_secure,
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        key=settings.session_cookie_name,
        path="/",
        samesite="lax",
        secure=settings.session_cookie_secure,
    )


def require_user(request: Request) -> SessionUser:
    token = request.cookies.get(settings.session_cookie_name)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        return load_session(token)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


def optional_user(request: Request) -> SessionUser | None:
    token = request.cookies.get(settings.session_cookie_name)
    if not token:
        return None
    try:
        return load_session(token)
    except ValueError:
        return None


async def require_cicd_owner(
    user: Annotated[SessionUser, Depends(require_user)],
) -> SessionUser:
    if await github.is_org_owner(user.login):
        return user
    raise HTTPException(
        status_code=403,
        detail="CICD 조직 owner만 사용할 수 있습니다",
    )


def can_view_orgs(login: str) -> bool:
    expected = (settings.ghes_inventory_login or "sk-inc").strip().lower()
    return login.strip().lower() == expected


def require_sk_inc(
    user: Annotated[SessionUser, Depends(require_user)],
) -> SessionUser:
    if can_view_orgs(user.login):
        return user
    raise HTTPException(
        status_code=403,
        detail="이 기능은 sk-inc 계정만 사용할 수 있습니다",
    )
