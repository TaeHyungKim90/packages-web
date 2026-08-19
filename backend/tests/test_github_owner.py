import httpx
import pytest
from app.services.github import is_org_owner


class _Resp:
    def __init__(self, status_code: int, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


class _Client:
    def __init__(self, resp: _Resp):
        self.resp = resp

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def get(self, url, headers=None, timeout=None):
        return self.resp


@pytest.mark.asyncio
async def test_is_org_owner_true_for_active_admin(monkeypatch):
    monkeypatch.setattr("app.services.github.settings.github_token", "tok")
    monkeypatch.setattr("app.services.github.settings.github_org", "CICD")
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: _Client(_Resp(200, {"role": "admin", "state": "active"})),
    )
    assert await is_org_owner("alice") is True


@pytest.mark.asyncio
async def test_is_org_owner_false_for_member(monkeypatch):
    monkeypatch.setattr("app.services.github.settings.github_token", "tok")
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: _Client(_Resp(200, {"role": "member", "state": "active"})),
    )
    assert await is_org_owner("bob") is False


@pytest.mark.asyncio
async def test_is_org_owner_false_for_404(monkeypatch):
    monkeypatch.setattr("app.services.github.settings.github_token", "tok")
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: _Client(_Resp(404)),
    )
    assert await is_org_owner("nobody") is False


@pytest.mark.asyncio
async def test_is_org_owner_false_without_token(monkeypatch):
    monkeypatch.setattr("app.services.github.settings.github_token", "")
    assert await is_org_owner("alice") is False
