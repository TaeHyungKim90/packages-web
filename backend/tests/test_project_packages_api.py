from app.config import settings
from app.deps import set_session_cookie
from app.services.project_packages import AggregatedRow, Snapshot
from app.services.session import SessionUser
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


def _authed(login: str = "sk-inc") -> TestClient:
    from starlette.responses import Response

    res = Response()
    set_session_cookie(res, SessionUser(login=login, name=login, avatar_url=None))
    cookie_header = res.headers.get("set-cookie", "")
    name = settings.session_cookie_name
    value = cookie_header.split("=", 1)[1].split(";", 1)[0]
    client.cookies.set(name, value)
    return client


def test_project_packages_requires_auth():
    client.cookies.clear()
    assert client.get("/api/project-packages").status_code == 401


def test_project_packages_forbidden():
    c = _authed("alice")
    assert c.get("/api/project-packages").status_code == 403


def test_project_packages_get_from_cache(monkeypatch):
    calls = {"health": 0}

    async def _health(_fmt: str):
        calls["health"] += 1
        raise AssertionError("GET must not call proxy-health")

    monkeypatch.setattr(
        "app.services.project_packages.ensure_all_proxy_health_cached", _health
    )
    monkeypatch.setattr(
        "app.services.project_packages.load_snapshot_cached",
        lambda: Snapshot(
            collected_at="2026-01-01T00:00:00+00:00",
            aggregated=[
                AggregatedRow(
                    format="pypi",
                    name="fastapi",
                    version="0.115.0",
                    imported_at="2026-08-16T00:00:00+00:00",
                    max_threat_level=8.6,
                    organizations=["AAC", "AAP"],
                )
            ],
        ),
    )
    c = _authed("sk-inc")
    response = c.get("/api/project-packages", params={"org": "AAC", "name": "fast"})
    assert response.status_code == 200
    body = response.json()
    assert body["items"][0]["organizations"] == ["AAC", "AAP"]
    assert body["items"][0]["max_threat_level"] == 8.6
    assert calls["health"] == 0


def test_project_packages_sync_mocked(monkeypatch):
    async def _sync(org=None):
        return Snapshot(
            collected_at="2026-01-02T00:00:00+00:00",
            projects=[],
            aggregated=[
                AggregatedRow(
                    format="npm",
                    name="react",
                    version="19.2.7",
                    organizations=["ABD"],
                )
            ],
        )

    monkeypatch.setattr("app.routers.project_packages.project_packages.sync", _sync)
    c = _authed("sk-inc")
    response = c.post("/api/project-packages/sync")
    assert response.status_code == 200
    assert response.json()["item_count"] == 1
