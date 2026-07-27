from fastapi import HTTPException, Request, Response

from app.config import settings
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
