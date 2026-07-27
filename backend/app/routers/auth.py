import secrets
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import RedirectResponse

from app.config import settings
from app.deps import clear_session_cookie, require_user, set_session_cookie
from app.schemas import UserResponse
from app.services import ghes_oauth
from app.services.session import SessionUser, sign_oauth_state, verify_oauth_state

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/login")
async def login() -> RedirectResponse:
    if not settings.github_oauth_client_id or not settings.github_oauth_client_secret:
        raise HTTPException(
            status_code=503,
            detail="GitHub OAuth is not configured",
        )
    state = sign_oauth_state(secrets.token_urlsafe(16))
    url = ghes_oauth.build_authorize_url(state=state)
    return RedirectResponse(url=url, status_code=302)


@router.get("/callback")
async def callback(
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    error_description: str | None = Query(default=None),
) -> RedirectResponse:
    frontend = settings.frontend_base_url.rstrip("/")

    if error:
        qs = urlencode({"error": error_description or error})
        return RedirectResponse(url=f"{frontend}/login?{qs}", status_code=302)

    if not code or not state:
        qs = urlencode({"error": "missing code or state"})
        return RedirectResponse(url=f"{frontend}/login?{qs}", status_code=302)

    try:
        verify_oauth_state(state)
    except ValueError:
        qs = urlencode({"error": "invalid or expired state"})
        return RedirectResponse(url=f"{frontend}/login?{qs}", status_code=302)

    try:
        access_token = await ghes_oauth.exchange_code_for_token(code)
        ghes_user = await ghes_oauth.fetch_authenticated_user(access_token)
    except (httpx.HTTPError, ValueError) as exc:
        qs = urlencode({"error": str(exc)})
        return RedirectResponse(url=f"{frontend}/login?{qs}", status_code=302)

    user = SessionUser(
        login=ghes_user.login,
        name=ghes_user.name,
        avatar_url=ghes_user.avatar_url,
    )
    redirect = RedirectResponse(url=f"{frontend}/search", status_code=302)
    set_session_cookie(redirect, user)
    return redirect


@router.post("/logout")
async def logout(response: Response) -> dict[str, str]:
    clear_session_cookie(response)
    return {"status": "ok"}


@router.get("/me", response_model=UserResponse)
async def me(request: Request) -> UserResponse:
    user = require_user(request)
    return UserResponse(
        login=user.login,
        name=user.name,
        avatar_url=user.avatar_url,
    )
