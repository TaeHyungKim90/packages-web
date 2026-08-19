from app.config import settings
from app.deps import set_session_cookie
from app.services.session import SessionUser
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

client = TestClient(app)


def _authed_client() -> TestClient:
    response = client.get("/health")
    assert response.status_code == 200

    # Attach session via a dummy response then copy cookie to client
    from starlette.responses import Response

    res = Response()
    set_session_cookie(res, SessionUser(login="tester", name="Tester", avatar_url=None))
    cookie_header = res.headers.get("set-cookie", "")
    # packages_web_session=...; ...
    name = settings.session_cookie_name
    value = cookie_header.split("=", 1)[1].split(";", 1)[0]
    client.cookies.set(name, value)
    return client


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_packages_requires_auth():
    client.cookies.clear()
    response = client.get("/api/packages/check", params={"format": "pypi", "name": "uv"})
    assert response.status_code == 401


def test_me_requires_auth():
    client.cookies.clear()
    response = client.get("/api/auth/me")
    assert response.status_code == 401


def test_me_with_session(monkeypatch):
    async def _yes(_login: str) -> bool:
        return True

    monkeypatch.setattr("app.routers.auth.github.is_org_owner", _yes)
    c = _authed_client()
    response = c.get("/api/auth/me")
    assert response.status_code == 200
    assert response.json()["login"] == "tester"
    assert response.json()["can_request"] is True


def test_me_can_request_false_for_member(monkeypatch):
    async def _no(_login: str) -> bool:
        return False

    monkeypatch.setattr("app.routers.auth.github.is_org_owner", _no)
    c = _authed_client()
    response = c.get("/api/auth/me")
    assert response.status_code == 200
    assert response.json()["can_request"] is False


def test_check_requires_name_when_authed():
    c = _authed_client()
    response = c.get("/api/packages/check", params={"format": "pypi", "name": "  "})
    assert response.status_code == 400


def test_check_rejects_unknown_format_when_authed():
    c = _authed_client()
    response = c.get(
        "/api/packages/check",
        params={"format": "cargo", "name": "serde"},
    )
    assert response.status_code == 400


def test_login_unconfigured_redirects_to_login(monkeypatch):
    monkeypatch.setattr(settings, "github_oauth_client_id", "")
    monkeypatch.setattr(settings, "github_oauth_client_secret", "")
    response = client.get("/api/auth/login", follow_redirects=False)
    assert response.status_code == 302
    assert "/login" in response.headers["location"]
    assert "OAuth" in response.headers["location"]


def test_login_redirects_when_configured(monkeypatch):
    monkeypatch.setattr(settings, "github_oauth_client_id", "cid")
    monkeypatch.setattr(settings, "github_oauth_client_secret", "secret")
    response = client.get("/api/auth/login", follow_redirects=False)
    assert response.status_code == 302
    assert "login/oauth/authorize" in response.headers["location"]
    assert "client_id=cid" in response.headers["location"]


def test_logout_clears_cookie():
    c = _authed_client()
    response = c.post("/api/auth/logout")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
