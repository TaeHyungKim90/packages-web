from app.config import settings
from app.deps import set_session_cookie
from app.schemas import GhesOrgsResponse
from app.services.ghes_inventory import InventoryOrg, InventoryRepo
from app.services.session import SessionUser
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


def _authed(login: str = "sk-inc") -> TestClient:
    from starlette.responses import Response

    res = Response()
    set_session_cookie(
        res, SessionUser(login=login, name=login, avatar_url=None)
    )
    cookie_header = res.headers.get("set-cookie", "")
    name = settings.session_cookie_name
    value = cookie_header.split("=", 1)[1].split(";", 1)[0]
    client.cookies.set(name, value)
    return client


def test_ghes_orgs_requires_auth():
    client.cookies.clear()
    response = client.get("/api/ghes-orgs")
    assert response.status_code == 401


def test_ghes_orgs_forbidden_for_other_user():
    c = _authed("alice")
    response = c.get("/api/ghes-orgs")
    assert response.status_code == 403


def test_ghes_orgs_ok_for_sk_inc(monkeypatch):
    async def _fake():
        return [
            InventoryOrg(
                name="CICD",
                managed=True,
                present=True,
                repos=[
                    InventoryRepo(name="pypiPackages", managed=True, present=True)
                ],
            )
        ]

    monkeypatch.setattr(
        "app.routers.ghes_inventory.ghes_inventory.build_inventory", _fake
    )
    c = _authed("sk-inc")
    response = c.get("/api/ghes-orgs")
    assert response.status_code == 200
    body = GhesOrgsResponse.model_validate(response.json())
    assert body.organizations[0].name == "CICD"
    assert body.organizations[0].managed is True


def test_ghes_orgs_put_saves(monkeypatch, tmp_path):
    yaml_path = tmp_path / "ghes-orgs.yaml"
    monkeypatch.setattr(
        "app.services.ghes_inventory.settings.ghes_orgs_yaml_path",
        str(yaml_path),
    )

    async def _fake():
        return [
            InventoryOrg(
                name="CICD",
                managed=True,
                present=True,
                repos=[
                    InventoryRepo(name="pypiPackages", managed=True, present=True)
                ],
            )
        ]

    monkeypatch.setattr(
        "app.routers.ghes_inventory.ghes_inventory.build_inventory", _fake
    )
    c = _authed("sk-inc")
    response = c.put(
        "/api/ghes-orgs",
        json={
            "organizations": [
                {
                    "name": "CICD",
                    "managed": True,
                    "repos": [{"name": "pypiPackages", "managed": True}],
                }
            ]
        },
    )
    assert response.status_code == 200
    assert yaml_path.is_file()
    text = yaml_path.read_text(encoding="utf-8")
    assert "CICD" in text
    assert "managed: true" in text


def test_me_can_view_orgs(monkeypatch):
    async def _no(_login: str) -> bool:
        return False

    monkeypatch.setattr("app.routers.auth.github.is_org_owner", _no)
    c = _authed("sk-inc")
    response = c.get("/api/auth/me")
    assert response.status_code == 200
    assert response.json()["can_view_orgs"] is True

    c2 = _authed("alice")
    response2 = c2.get("/api/auth/me")
    assert response2.status_code == 200
    assert response2.json()["can_view_orgs"] is False
