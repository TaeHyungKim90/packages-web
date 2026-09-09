import httpx
import pytest
from app.config import settings
from app.deps import set_session_cookie
from app.schemas import ProxyHealthResponse
from app.services.nexus import blob_created_map, item_blob_created
from app.services.nexus_health import (
    _candidate_repos,
    fetch_proxy_health,
    map_license,
    map_vulnerability,
)
from app.services.session import SessionUser
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


def _authed_client(login: str = "tester") -> TestClient:
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


def _patch_owner(monkeypatch, *, is_owner: bool) -> None:
    async def _check(_login: str) -> bool:
        return is_owner

    monkeypatch.setattr("app.routers.proxy_health.github.is_org_owner", _check)
    monkeypatch.setattr("app.deps.github.is_org_owner", _check)


def test_map_vulnerability_npm():
    item = map_vulnerability(
        {
            "componentIdentifier": {
                "format": "npm",
                "coordinates": {"packageId": "pdfjs-dist", "version": "5.7.284"},
            },
            "url": "https://www.cve.org/CVERecord?id=CVE-2026-16633",
            "reference": "CVE-2026-16633",
            "score": 8.6,
        }
    )
    assert item is not None
    assert item.artifact == "pdfjs-dist"
    assert item.version == "5.7.284"
    assert item.problem_code == "CVE-2026-16633"
    assert item.threat_level == 8.6
    assert "CVE-2026-16633" in item.problem_url


def test_map_vulnerability_pypi_wheel():
    item = map_vulnerability(
        {
            "componentIdentifier": {
                "format": "pypi",
                "coordinates": {
                    "name": "aiohttp",
                    "version": "3.14.1",
                    "extension": "whl",
                },
            },
            "reference": "CVE-2026-59881",
            "score": 6.9,
        }
    )
    assert item is not None
    assert item.artifact == "aiohttp"
    assert item.version == "3.14.1"
    assert item.problem_url.endswith("CVE-2026-59881")


def test_map_license_security_count():
    item = map_license(
        {
            "componentIdentifier": {
                "format": "nuget",
                "coordinates": {"packageId": "Newtonsoft.Json", "version": "13.0.3"},
            },
            "declaredLicenses": ["MIT"],
            "observedLicenses": ["Not Supported"],
            "effectiveLicenseThreat": "LIBERAL",
            "securityCounters": {"Critical": 1, "Severe": 2, "Moderate": 0},
        }
    )
    assert item is not None
    assert item.artifact == "Newtonsoft.Json"
    assert item.declared_license == "MIT"
    assert item.license_threat == "LIBERAL"
    assert item.security_issues == 3


def test_candidate_repos_prefers_health():
    from app.config import ECOSYSTEM_MAP

    repos = _candidate_repos(ECOSYSTEM_MAP["npm"])
    assert repos[0] == "npm-proxy-health"
    assert "npm-proxy" in repos


class _Resp:
    def __init__(self, status_code: int, payload=None, text: str = ""):
        self.status_code = status_code
        self._payload = payload
        self.text = text or ""
        self.request = httpx.Request("GET", "https://nexus.example/x")

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "error", request=self.request, response=httpx.Response(self.status_code)
            )


class _FakeClient:
    def __init__(self, routes: dict[str, _Resp]):
        self.routes = routes

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def get(self, url, auth=None, timeout=None, follow_redirects=None, params=None):
        full = url
        if params:
            from urllib.parse import urlencode

            full = f"{url}?{urlencode(params)}"
        for key in sorted(self.routes, key=len, reverse=True):
            if key in full:
                return self.routes[key]
        return _Resp(404)


@pytest.mark.asyncio
async def test_fetch_falls_back_to_proxy_repo(monkeypatch):
    security = {
        "aaData": [
            {
                "componentIdentifier": {
                    "format": "npm",
                    "coordinates": {"packageId": "lodash", "version": "4.17.21"},
                },
                "reference": "CVE-2021-23337",
                "score": 7.2,
            }
        ]
    }
    licenses = {"aaData": []}
    meta = {
        "repositoryName": "npm-proxy",
        "lastAnalyzedDate": 1_700_000_000_000,
        "detailUrl": "/service/rest/healthcheck/healthCheckDetail/npm-proxy/current/details.html",
    }

    class _Client(_FakeClient):
        def __init__(self, *args, **kwargs):
            super().__init__(
                {
                    "healthcheck/npm-proxy-health": _Resp(404),
                    "healthcheck/npm-proxy": _Resp(200, meta),
                    "healthCheckDetail/npm-proxy/current/security.json": _Resp(
                        200, security
                    ),
                    "healthCheckDetail/npm-proxy/current/licenses.json": _Resp(
                        200, licenses
                    ),
                }
            )

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    result = await fetch_proxy_health("npm")
    assert result.repository == "npm-proxy"
    assert result.vulnerabilities[0].artifact == "lodash"
    assert result.generated_at is not None


@pytest.mark.asyncio
async def test_fetch_follows_current_redirect(monkeypatch):
    meta = {
        "repositoryName": "npm-proxy-health",
        "lastAnalyzedDate": 1_700_000_000_000,
        "detailUrl": (
            "/service/rest/healthcheck/healthCheckDetail/"
            "npm-proxy-health/current/details.html"
        ),
    }
    security = {
        "aaData": [
            {
                "componentIdentifier": {
                    "format": "npm",
                    "coordinates": {"packageId": "left-pad", "version": "1.3.0"},
                },
                "reference": "CVE-2018-0001",
                "score": 5.0,
            }
        ]
    }

    class _Client(_FakeClient):
        def __init__(self, *args, **kwargs):
            super().__init__(
                {
                    "healthcheck/npm-proxy-health": _Resp(200, meta),
                    "npm-proxy-health/current/security.json": _Resp(200, security),
                    "npm-proxy-health/current/licenses.json": _Resp(200, {"aaData": []}),
                }
            )

        async def get(self, url, auth=None, timeout=None, follow_redirects=None, params=None):
            assert follow_redirects is True
            return await super().get(
                url,
                auth=auth,
                timeout=timeout,
                follow_redirects=follow_redirects,
                params=params,
            )

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    result = await fetch_proxy_health("npm")
    assert result.repository == "npm-proxy-health"
    assert result.vulnerabilities[0].artifact == "left-pad"


@pytest.mark.asyncio
async def test_fetch_uses_health_repo(monkeypatch):
    meta = {
        "repositoryName": "pypi-proxy-health",
        "lastAnalyzedDate": 1_700_000_000_000,
        "detailUrl": (
            "/service/rest/healthcheck/healthCheckDetail/"
            "pypi-proxy-health/current/details.html"
        ),
    }

    class _Client(_FakeClient):
        def __init__(self, *args, **kwargs):
            super().__init__(
                {
                    "healthcheck/pypi-proxy-health": _Resp(200, meta),
                    "pypi-proxy-health/current/security.json": _Resp(200, {"aaData": []}),
                    "pypi-proxy-health/current/licenses.json": _Resp(200, {"aaData": []}),
                }
            )

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    result = await fetch_proxy_health("pypi")
    assert result.repository == "pypi-proxy-health"
    assert result.vulnerabilities == []


def test_item_blob_created_picks_latest_asset():
    created = item_blob_created(
        {
            "name": "foo",
            "version": "1.0.0",
            "assets": [
                {"blobCreated": "2026-08-16T00:00:00+00:00"},
                {"blobCreated": "2026-08-18T12:00:00+00:00"},
            ],
        }
    )
    assert created is not None
    assert created.startswith("2026-08-18T12:00:00")
    assert item_blob_created({"name": "foo", "version": "1.0.0"}) is None
    millis = item_blob_created(
        {"name": "foo", "version": "1.0.0", "blobCreated": 1_700_000_000_000}
    )
    assert millis is not None


@pytest.mark.asyncio
async def test_blob_created_pypi_mixed_case_apscheduler():
    hosted = {
        "items": [
            {
                "name": "apscheduler",
                "version": "3.10.4",
                "format": "pypi",
                "assets": [{"blobCreated": "2026-08-18T00:00:00+00:00"}],
            }
        ]
    }

    class _Client(_FakeClient):
        def __init__(self, *args, **kwargs):
            super().__init__({})

        async def get(self, url, auth=None, timeout=None, follow_redirects=None, params=None):
            assert (params or {}).get("q") == "APScheduler"
            repo = (params or {}).get("repository")
            if repo == "pypi-hosted":
                return _Resp(200, hosted)
            return _Resp(404)

    dates, hosted_keys = await blob_created_map(
        _Client(),
        hosted_repo="pypi-hosted",
        health_repo="pypi-proxy-health",
        package_format="pypi",
        keys={("APScheduler", "3.10.4")},
    )
    assert dates[("apscheduler", "3.10.4")].startswith("2026-08-18T00:00:00")
    assert ("apscheduler", "3.10.4") in hosted_keys


@pytest.mark.asyncio
async def test_blob_created_hosted_then_health_per_version():
    hosted = {
        "items": [
            {
                "name": "foo",
                "version": "1.0.0",
                "format": "pypi",
                "assets": [{"blobCreated": "2026-08-16T00:00:00+00:00"}],
            }
        ]
    }
    health = {
        "items": [
            {
                "name": "foo",
                "version": "1.0.2",
                "format": "pypi",
                "assets": [{"blobCreated": "2026-08-18T00:00:00+00:00"}],
            }
        ]
    }

    class _Client(_FakeClient):
        def __init__(self, *args, **kwargs):
            super().__init__({})

        async def get(self, url, auth=None, timeout=None, follow_redirects=None, params=None):
            repo = (params or {}).get("repository")
            if repo == "pypi-hosted":
                return _Resp(200, hosted)
            if repo == "pypi-proxy-health":
                return _Resp(200, health)
            return _Resp(404)

    dates, hosted_keys = await blob_created_map(
        _Client(),
        hosted_repo="pypi-hosted",
        health_repo="pypi-proxy-health",
        package_format="pypi",
        keys={("foo", "1.0.0"), ("foo", "1.0.2")},
    )
    assert dates[("foo", "1.0.0")] == "2026-08-16T00:00:00+00:00"
    assert dates[("foo", "1.0.2")] == "2026-08-18T00:00:00+00:00"
    assert ("foo", "1.0.0") in hosted_keys
    assert ("foo", "1.0.2") not in hosted_keys


@pytest.mark.asyncio
async def test_fetch_attaches_imported_at_from_hosted_and_health(monkeypatch):
    meta = {
        "repositoryName": "pypi-proxy-health",
        "lastAnalyzedDate": 1_700_000_000_000,
        "detailUrl": (
            "/service/rest/healthcheck/healthCheckDetail/"
            "pypi-proxy-health/current/details.html"
        ),
    }
    security = {
        "aaData": [
            {
                "componentIdentifier": {
                    "format": "pypi",
                    "coordinates": {"name": "foo", "version": "1.0.0"},
                },
                "reference": "CVE-1",
                "score": 5.0,
            },
            {
                "componentIdentifier": {
                    "format": "pypi",
                    "coordinates": {"name": "foo", "version": "1.0.2"},
                },
                "reference": "CVE-1",
                "score": 5.0,
            },
        ]
    }

    class _Client(_FakeClient):
        def __init__(self, *args, **kwargs):
            super().__init__(
                {
                    "healthcheck/pypi-proxy-health": _Resp(200, meta),
                    "pypi-proxy-health/current/security.json": _Resp(200, security),
                    "pypi-proxy-health/current/licenses.json": _Resp(200, {"aaData": []}),
                }
            )

        async def get(self, url, auth=None, timeout=None, follow_redirects=None, params=None):
            repo = (params or {}).get("repository")
            if repo == "pypi-hosted":
                return _Resp(
                    200,
                    {
                        "items": [
                            {
                                "name": "foo",
                                "version": "1.0.0",
                                "format": "pypi",
                                "assets": [
                                    {"blobCreated": "2026-08-16T00:00:00+00:00"}
                                ],
                            }
                        ]
                    },
                )
            if repo == "pypi-proxy-health":
                return _Resp(
                    200,
                    {
                        "items": [
                            {
                                "name": "foo",
                                "version": "1.0.2",
                                "format": "pypi",
                                "assets": [
                                    {"blobCreated": "2026-08-18T00:00:00+00:00"}
                                ],
                            }
                        ]
                    },
                )
            return await super().get(
                url,
                auth=auth,
                timeout=timeout,
                follow_redirects=follow_redirects,
                params=params,
            )

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    result = await fetch_proxy_health("pypi")
    by_version = {row.version: row.imported_at for row in result.vulnerabilities}
    assert by_version["1.0.0"] == "2026-08-16T00:00:00+00:00"
    assert by_version["1.0.2"] == "2026-08-18T00:00:00+00:00"
    hosted_by_version = {row.version: row.in_hosted for row in result.vulnerabilities}
    assert hosted_by_version["1.0.0"] is True
    assert hosted_by_version["1.0.2"] is False


def test_proxy_health_requires_auth():
    client.cookies.clear()
    response = client.get("/api/proxy-health/pypi")
    assert response.status_code == 401


def test_proxy_health_rejects_unknown_eco():
    c = _authed_client()
    response = c.get("/api/proxy-health/maven")
    assert response.status_code == 400


def test_proxy_health_success(monkeypatch):
    _patch_owner(monkeypatch, is_owner=True)

    async def _fake(eco: str, *, force_refresh: bool = False) -> ProxyHealthResponse:
        assert eco == "nuget"
        assert force_refresh is False
        return ProxyHealthResponse(
            ecosystem=eco,
            repository="nuget-proxy-health",
            generated_at="2026-01-01T00:00:00+00:00",
            vulnerabilities=[],
            licenses=[],
        )

    monkeypatch.setattr(
        "app.routers.proxy_health.get_proxy_health_cached", _fake
    )
    c = _authed_client()
    response = c.get("/api/proxy-health/nuget")
    assert response.status_code == 200
    assert response.json()["repository"] == "nuget-proxy-health"


def test_proxy_health_refresh_query_forces_live(monkeypatch):
    _patch_owner(monkeypatch, is_owner=True)
    seen = {"refresh": None}

    async def _fake(eco: str, *, force_refresh: bool = False) -> ProxyHealthResponse:
        seen["refresh"] = force_refresh
        return ProxyHealthResponse(
            ecosystem=eco,
            repository="nuget-proxy-health",
            generated_at="2026-01-01T00:00:00+00:00",
            fetched_at="2026-09-08T00:00:00+00:00",
            vulnerabilities=[],
            licenses=[],
        )

    monkeypatch.setattr(
        "app.routers.proxy_health.get_proxy_health_cached", _fake
    )
    c = _authed_client()
    response = c.get("/api/proxy-health/nuget?refresh=true")
    assert response.status_code == 200
    assert seen["refresh"] is True
    assert response.json()["fetched_at"] == "2026-09-08T00:00:00+00:00"


def test_proxy_health_member_reads_db_only(monkeypatch):
    _patch_owner(monkeypatch, is_owner=False)
    cached_called = {"value": False}

    async def _cached(_eco: str) -> ProxyHealthResponse:
        cached_called["value"] = True
        raise AssertionError("member must not call get_proxy_health_cached")

    def _from_db(eco: str) -> ProxyHealthResponse:
        assert eco == "pypi"
        return ProxyHealthResponse(
            ecosystem=eco,
            repository="pypi-proxy-health",
            generated_at="2026-01-01T00:00:00+00:00",
            vulnerabilities=[],
            licenses=[],
            vulnerability_overrides=[],
        )

    monkeypatch.setattr(
        "app.routers.proxy_health.get_proxy_health_cached", _cached
    )
    monkeypatch.setattr(
        "app.routers.proxy_health.get_proxy_health_from_db", _from_db
    )
    c = _authed_client(login="member")
    response = c.get("/api/proxy-health/pypi")
    assert response.status_code == 200
    assert response.json()["repository"] == "pypi-proxy-health"
    assert cached_called["value"] is False


def test_proxy_health_member_db_missing_404(monkeypatch):
    _patch_owner(monkeypatch, is_owner=False)

    def _from_db(_eco: str) -> ProxyHealthResponse:
        raise LookupError("No cached proxy health data for ecosystem: pypi")

    monkeypatch.setattr(
        "app.routers.proxy_health.get_proxy_health_from_db", _from_db
    )
    c = _authed_client(login="member")
    response = c.get("/api/proxy-health/pypi")
    assert response.status_code == 404


def test_proxy_health_member_cannot_put_override(monkeypatch):
    _patch_owner(monkeypatch, is_owner=False)
    c = _authed_client(login="member")
    response = c.put(
        "/api/proxy-health/pypi/overrides",
        json={
            "problem_code": "CVE-1",
            "artifact": "foo",
            "fixed_version": "1.2.3",
            "remark": "x",
        },
    )
    assert response.status_code == 403


def test_proxy_health_member_cannot_delete_override(monkeypatch):
    _patch_owner(monkeypatch, is_owner=False)
    c = _authed_client(login="member")
    response = c.request(
        "DELETE",
        "/api/proxy-health/pypi/overrides",
        json={"problem_code": "CVE-1", "artifact": "foo"},
    )
    assert response.status_code == 403


def test_proxy_health_snapshot_from_db(monkeypatch):
    def _fake(eco: str) -> ProxyHealthResponse:
        assert eco == "pypi"
        return ProxyHealthResponse(
            ecosystem=eco,
            repository="pypi-proxy-health",
            generated_at="2026-01-01T00:00:00+00:00",
            vulnerabilities=[],
            licenses=[],
            vulnerability_overrides=[],
        )

    monkeypatch.setattr(
        "app.routers.proxy_health.get_proxy_health_from_db", _fake
    )
    c = _authed_client()
    response = c.get("/api/proxy-health/pypi/snapshot")
    assert response.status_code == 200
    assert response.json()["repository"] == "pypi-proxy-health"


def test_proxy_health_snapshot_not_found(monkeypatch):
    def _fake(_eco: str) -> ProxyHealthResponse:
        raise LookupError("No cached proxy health data for ecosystem: pypi")

    monkeypatch.setattr(
        "app.routers.proxy_health.get_proxy_health_from_db", _fake
    )
    c = _authed_client()
    response = c.get("/api/proxy-health/pypi/snapshot")
    assert response.status_code == 404


def test_proxy_health_maps_nexus_401_to_502(monkeypatch):
    _patch_owner(monkeypatch, is_owner=True)

    async def _fake(_eco: str, **_kwargs) -> ProxyHealthResponse:
        request = httpx.Request("GET", "https://nexus.example/health")
        response = httpx.Response(401, text="Unauthorized", request=request)
        raise httpx.HTTPStatusError("401", request=request, response=response)

    monkeypatch.setattr(
        "app.routers.proxy_health.get_proxy_health_cached", _fake
    )
    c = _authed_client()
    response = c.get("/api/proxy-health/pypi")
    assert response.status_code == 502
    assert "Nexus API error" in response.json()["detail"]


def test_proxy_health_maps_nexus_403_to_502(monkeypatch):
    _patch_owner(monkeypatch, is_owner=True)

    async def _fake(_eco: str, **_kwargs) -> ProxyHealthResponse:
        request = httpx.Request("GET", "https://nexus.example/health")
        response = httpx.Response(403, text="Forbidden", request=request)
        raise httpx.HTTPStatusError("403", request=request, response=response)

    monkeypatch.setattr(
        "app.routers.proxy_health.get_proxy_health_cached", _fake
    )
    c = _authed_client()
    response = c.get("/api/proxy-health/pypi")
    assert response.status_code == 502
    assert "Nexus API error" in response.json()["detail"]
