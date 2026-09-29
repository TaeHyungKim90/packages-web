import pytest
from app.config import settings
from app.db import connect, init_schema
from app.deps import set_session_cookie
from app.services import ghes_members
from app.services.session import SessionUser
from fastapi.testclient import TestClient
from main import app
from starlette.responses import Response

client = TestClient(app)


def _authed(login: str = "sk-inc") -> TestClient:
    res = Response()
    set_session_cookie(res, SessionUser(login=login, name=login, avatar_url=None))
    cookie_header = res.headers.get("set-cookie", "")
    name = settings.session_cookie_name
    value = cookie_header.split("=", 1)[1].split(";", 1)[0]
    client.cookies.set(name, value)
    return client


def test_list_cached_members_empty():
    init_schema()
    conn = connect()
    conn.execute("DELETE FROM ghes_member_org")
    conn.execute("DELETE FROM ghes_member")
    conn.execute("DELETE FROM ghes_member_meta")
    conn.commit()
    conn.close()

    data = ghes_members.list_cached_members()
    assert data.members == []
    assert data.synced_at is None


def test_save_and_list_members_skips_sk_inc_org_and_labels_admin(monkeypatch):
    monkeypatch.setattr(
        "app.services.ghes_members.settings.ghes_inventory_login",
        "sk-inc",
    )
    init_schema()
    ghes_members._save_members(
        [
            {"login": "sk-inc", "id": 1, "type": "User", "site_admin": True},
            {
                "login": "hp00407",
                "id": 2,
                "name": "HP",
                "type": "User",
                "site_admin": False,
            },
            {"login": "ACM", "id": 3, "type": "Organization"},
            {"login": "dependabot[bot]", "id": 4, "type": "Bot"},
            {"login": "actions-admin", "id": 5, "type": "User", "site_admin": True},
            {"login": "ghost", "id": 6, "type": "User"},
        ],
        {
            "sk-inc": ["sk-inc", "CICD"],
            "hp00407": ["ACM", "sk-inc", "AAP"],
            "acm": ["ACM"],
            "dependabot[bot]": ["CICD"],
            "actions-admin": ["CICD"],
            "ghost": ["ACM"],
        },
        synced_at="2026-09-14T00:00:00+00:00",
    )
    data = ghes_members.list_cached_members()
    assert data.synced_at == "2026-09-14T00:00:00+00:00"
    by_login = {m.login: m for m in data.members}
    assert "ACM" not in by_login
    assert "dependabot[bot]" not in by_login
    assert "actions-admin" not in by_login
    assert "ghost" not in by_login
    assert by_login["sk-inc"].organizations_label == "관리"
    assert "sk-inc" not in by_login["sk-inc"].organizations
    assert by_login["hp00407"].organizations == ["AAP", "ACM"]
    assert by_login["hp00407"].organizations_label == "AAP,ACM"


def test_ghes_members_requires_auth():
    client.cookies.clear()
    response = client.get("/api/ghes-members")
    assert response.status_code == 401


def test_ghes_members_forbidden_for_other_user():
    c = _authed("alice")
    response = c.get("/api/ghes-members")
    assert response.status_code == 403


def test_ghes_members_api():
    init_schema()
    ghes_members._save_members(
        [{"login": "hp00407", "id": 2, "type": "User"}],
        {"hp00407": ["ACM"]},
        synced_at="2026-09-14T00:00:00+00:00",
    )
    c = _authed("sk-inc")
    response = c.get("/api/ghes-members")
    assert response.status_code == 200
    body = response.json()
    assert body["synced_at"] == "2026-09-14T00:00:00+00:00"
    assert body["members"][0]["login"] == "hp00407"
    assert body["members"][0]["organizations_label"] == "ACM"


@pytest.mark.asyncio
async def test_list_users_continues_after_short_page():
    """GHES may return < per_page while more users exist after last id."""
    calls: list[int] = []

    class FakeResponse:
        def __init__(self, payload, status_code=200):
            self._payload = payload
            self.status_code = status_code
            self.text = ""

        def json(self):
            return self._payload

    class FakeClient:
        async def get(self, url, params=None, headers=None, timeout=None):
            since = int((params or {}).get("since") or 0)
            calls.append(since)
            if since == 0:
                return FakeResponse(
                    [
                        {"login": "hk00685", "id": 124, "type": "User"},
                    ]
                )
            if since == 124:
                return FakeResponse(
                    [
                        {"login": "CFA", "id": 125, "type": "Organization"},
                        {"login": "hk00697", "id": 126, "type": "User"},
                    ]
                )
            return FakeResponse([])

    users = await ghes_members._list_users(FakeClient())
    assert [u["login"] for u in users] == ["hk00685", "hk00697"]
    assert calls == [0, 124, 126]
