import secrets
from urllib.parse import urlencode

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import RedirectResponse

from app.config import settings
from app.deps import clear_session_cookie, require_user, set_session_cookie
from app.schemas import UserResponse
from app.services import ghes_oauth, github
from app.services.session import SessionUser, sign_oauth_state, verify_oauth_state

router = APIRouter(prefix="/auth", tags=["auth"])


def _frontend_login(error: str | None = None) -> RedirectResponse:
    frontend = settings.frontend_base_url.rstrip("/")
    if error:
        qs = urlencode({"error": error})
        return RedirectResponse(url=f"{frontend}/login?{qs}", status_code=302)
    return RedirectResponse(url=f"{frontend}/login", status_code=302)


@router.get("/login")
async def login() -> RedirectResponse:
    if not settings.github_oauth_client_id or not settings.github_oauth_client_secret:
        return _frontend_login("GitHub OAuth is not configured")
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
    if error:
        return _frontend_login(error_description or error)

    if not code or not state:
        return _frontend_login("missing code or state")

    try:
        verify_oauth_state(state)
    except ValueError:
        return _frontend_login("invalid or expired state")

    try:
        access_token = await ghes_oauth.exchange_code_for_token(code)
        ghes_user = await ghes_oauth.fetch_authenticated_user(access_token)
    except Exception as exc:
        return _frontend_login(str(exc) or "login failed")

    user = SessionUser(
        login=ghes_user.login,
        name=ghes_user.name,
        avatar_url=ghes_user.avatar_url,
    )
    redirect = RedirectResponse(
        url=f"{settings.frontend_base_url.rstrip('/')}/search",
        status_code=302,
    )
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
        can_request=await github.is_org_owner(user.login),
    )
