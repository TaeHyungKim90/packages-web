from dataclasses import dataclass

import httpx

from app.config import settings

OAUTH_AUTHORIZE_PATH = "/login/oauth/authorize"
OAUTH_TOKEN_PATH = "/login/oauth/access_token"
OAUTH_SCOPE = "read:user"


@dataclass(frozen=True)
class GhesUser:
    login: str
    name: str | None
    avatar_url: str | None


def build_authorize_url(*, state: str) -> str:
    base = settings.github_base_url.rstrip("/")
    params = httpx.QueryParams(
        {
            "client_id": settings.github_oauth_client_id,
            "redirect_uri": settings.oauth_redirect_uri,
            "scope": OAUTH_SCOPE,
            "state": state,
        }
    )
    return f"{base}{OAUTH_AUTHORIZE_PATH}?{params}"


async def exchange_code_for_token(code: str) -> str:
    url = f"{settings.github_base_url.rstrip('/')}{OAUTH_TOKEN_PATH}"
    headers = {"Accept": "application/json"}
    payload = {
        "client_id": settings.github_oauth_client_id,
        "client_secret": settings.github_oauth_client_secret,
        "code": code,
        "redirect_uri": settings.oauth_redirect_uri,
    }
    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=payload, headers=headers, timeout=30.0)
        response.raise_for_status()
        data = response.json()

    token = data.get("access_token")
    if not token:
        error = data.get("error_description") or data.get("error") or "token exchange failed"
        raise ValueError(str(error))
    return str(token)


async def fetch_authenticated_user(access_token: str) -> GhesUser:
    url = f"{settings.github_api_base.rstrip('/')}/user"
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {access_token}",
    }
    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers, timeout=30.0)
        response.raise_for_status()
        data = response.json()

    login = data.get("login")
    if not login:
        raise ValueError("GitHub user response missing login")
    return GhesUser(
        login=str(login),
        name=data.get("name"),
        avatar_url=data.get("avatar_url"),
    )
