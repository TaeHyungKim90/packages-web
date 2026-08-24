import pytest
from app.config import settings
from app.deps import set_session_cookie
from app.services.github import PullRequest
from app.services.session import SessionUser
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


def _authed() -> TestClient:
    from starlette.responses import Response

    res = Response()
    set_session_cookie(res, SessionUser(login="tester", name="Tester", avatar_url=None))
    cookie_header = res.headers.get("set-cookie", "")
    name = settings.session_cookie_name
    value = cookie_header.split("=", 1)[1].split(";", 1)[0]
    client.cookies.set(name, value)
    return client


@pytest.fixture(autouse=True)
def _cicd_owner(monkeypatch):
    async def _yes(_login: str) -> bool:
        return True

    monkeypatch.setattr("app.services.github.is_org_owner", _yes)
    monkeypatch.setattr("app.deps.github.is_org_owner", _yes)


def test_request_pypi_requires_auth():
    client.cookies.clear()
    response = client.post(
        "/api/request/pypi",
        json={"packages": [{"name": "requests", "version": "2.32.3"}]},
    )
    assert response.status_code == 401


def test_request_pypi_forbidden_if_not_owner(monkeypatch):
    async def _no(_login: str) -> bool:
        return False

    monkeypatch.setattr("app.services.github.is_org_owner", _no)
    monkeypatch.setattr("app.deps.github.is_org_owner", _no)
    c = _authed()
    response = c.post(
        "/api/request/pypi",
        json={"packages": [{"name": "requests", "version": "2.32.3"}]},
    )
    assert response.status_code == 403


def test_request_pypi_requires_token(monkeypatch):
    monkeypatch.setattr(settings, "github_token", "")
    c = _authed()
    response = c.post(
        "/api/request/pypi",
        json={"packages": [{"name": "requests", "version": "2.32.3"}]},
    )
    assert response.status_code == 503


async def _fake_submit(*, eco, packages, requested_by):
    first = packages[0]
    pr = PullRequest(
        number=42,
        html_url="https://github.sk-inc.com/CICD/pypiPackages/pull/42",
        state="open",
        merged=False,
        title=f"request: {first[0]}=={first[1]}",
        node_id="PR_42",
    )
    return pr, "request/20260101-web-requests", True, "MERGE"


def test_request_pypi_success(monkeypatch):
    monkeypatch.setattr(settings, "github_token", "dummy-token")
    monkeypatch.setattr("app.routers.package_request.gitops.submit_package_request", _fake_submit)
    c = _authed()
    response = c.post(
        "/api/request/pypi",
        json={"packages": [{"name": "requests", "version": "2.32.3"}]},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["pr_number"] == 42
    assert data["packages"][0]["name"] == "requests"
    assert data["requested_by"] == "tester"
    assert "pull/42" in data["pr_url"]


def test_request_pypi_batch(monkeypatch):
    monkeypatch.setattr(settings, "github_token", "dummy-token")
    monkeypatch.setattr("app.routers.package_request.gitops.submit_package_request", _fake_submit)
    c = _authed()
    response = c.post(
        "/api/request/pypi",
        json={
            "packages": [
                {"name": "requests", "version": "2.32.3"},
                {"name": "httpx", "version": "0.28.1"},
            ]
        },
    )
    assert response.status_code == 200
    assert len(response.json()["packages"]) == 2


async def _fake_validate(*, eco, name, version):
    return [
        {
            "key": "upstream",
            "label": "업스트림 버전 존재",
            "passed": True,
            "detail": f"PyPI에 {name}=={version} 확인됨.",
        },
        {
            "key": "hosted",
            "label": "Hosted에 이미 등록됨",
            "passed": True,
            "detail": "pypi-hosted에 없음",
        },
        {
            "key": "inventory",
            "label": "Inventory에 이미 등록됨",
            "passed": True,
            "detail": "inventory에 없음",
        },
        {
            "key": "requests",
            "label": "요청 목록 중복 없음",
            "passed": True,
            "detail": "요청 목록에 없습니다.",
        },
    ]


def test_validate_pypi_requires_auth():
    client.cookies.clear()
    response = client.post(
        "/api/request/pypi/validate",
        json={"packages": [{"name": "requests", "version": "2.32.3"}]},
    )
    assert response.status_code == 401


def test_validate_pypi_success(monkeypatch):
    monkeypatch.setattr(settings, "github_token", "dummy-token")
    monkeypatch.setattr(
        "app.routers.package_request.gitops.validate_package_request",
        _fake_validate,
    )
    c = _authed()
    response = c.post(
        "/api/request/pypi/validate",
        json={"packages": [{"name": "requests", "version": "2.32.3"}]},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["can_request"] is True
    assert data["items"][0]["name"] == "requests"
    assert len(data["items"][0]["checks"]) == 5
    assert all(c["passed"] for c in data["items"][0]["checks"])


def test_validate_pypi_blocked(monkeypatch):
    async def _blocked(*, eco, name, version):
        return [
            {
                "key": "upstream",
                "label": "업스트림 버전 존재",
                "passed": False,
                "detail": "PyPI에 requests==9.9.9이(가) 없습니다.",
            },
            {
                "key": "hosted",
                "label": "Hosted에 이미 등록됨",
                "passed": True,
                "detail": "pypi-hosted에 없음",
            },
            {
                "key": "inventory",
                "label": "Inventory에 이미 등록됨",
                "passed": True,
                "detail": "inventory에 없음",
            },
            {
                "key": "requests",
                "label": "요청 목록 중복 없음",
                "passed": True,
                "detail": "요청 목록에 없습니다.",
            },
        ]

    monkeypatch.setattr(settings, "github_token", "dummy-token")
    monkeypatch.setattr(
        "app.routers.package_request.gitops.validate_package_request",
        _blocked,
    )
    c = _authed()
    response = c.post(
        "/api/request/pypi/validate",
        json={"packages": [{"name": "requests", "version": "2.32.3"}]},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["can_request"] is False
    assert data["items"][0]["checks"][0]["passed"] is False


def test_status_delivery_pending(monkeypatch):
    async def _merge_if_ready(owner, repo, number):
        return PullRequest(
            number=number,
            html_url=f"https://github.sk-inc.com/CICD/pypiPackages/pull/{number}",
            state="open",
            merged=False,
            title="request: requests==2.32.3",
            node_id="PR_1",
        )

    async def _raw(owner, repo, number):
        return {"mergeable_state": "blocked"}

    monkeypatch.setattr(settings, "github_token", "dummy-token")
    monkeypatch.setattr(
        "app.routers.package_request.github.merge_if_ready", _merge_if_ready
    )
    monkeypatch.setattr("app.routers.package_request.github.get_pull_raw", _raw)
    c = _authed()
    response = c.get(
        "/api/request/pypi/7",
        params={"packages": "requests==2.32.3"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["merged"] is False
    assert data["delivery"] == "pending"
    assert data["packages"][0]["in_hosted"] is False


def test_status_delivery_delivering(monkeypatch):
    async def _merge_if_ready(owner, repo, number):
        return PullRequest(
            number=number,
            html_url=f"https://github.sk-inc.com/CICD/pypiPackages/pull/{number}",
            state="closed",
            merged=True,
            title="request: requests==2.32.3",
            node_id="PR_1",
        )

    async def _raw(owner, repo, number):
        return {"mergeable_state": "unknown"}

    async def _hosted(eco, name, version):
        return False

    monkeypatch.setattr(settings, "github_token", "dummy-token")
    monkeypatch.setattr(
        "app.routers.package_request.github.merge_if_ready", _merge_if_ready
    )
    monkeypatch.setattr("app.routers.package_request.github.get_pull_raw", _raw)
    monkeypatch.setattr(
        "app.routers.package_request.gitops.hosted_has_exact", _hosted
    )
    c = _authed()
    response = c.get(
        "/api/request/pypi/7",
        params={"packages": "requests==2.32.3"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["merged"] is True
    assert data["delivery"] == "delivering"
    assert data["packages"][0]["in_hosted"] is False


def test_status_delivery_done(monkeypatch):
    async def _merge_if_ready(owner, repo, number):
        return PullRequest(
            number=number,
            html_url=f"https://github.sk-inc.com/CICD/pypiPackages/pull/{number}",
            state="closed",
            merged=True,
            title="request: requests==2.32.3",
            node_id="PR_1",
        )

    async def _raw(owner, repo, number):
        return {"mergeable_state": "unknown"}

    async def _hosted(eco, name, version):
        return True

    monkeypatch.setattr(settings, "github_token", "dummy-token")
    monkeypatch.setattr(
        "app.routers.package_request.github.merge_if_ready", _merge_if_ready
    )
    monkeypatch.setattr("app.routers.package_request.github.get_pull_raw", _raw)
    monkeypatch.setattr(
        "app.routers.package_request.gitops.hosted_has_exact", _hosted
    )
    c = _authed()
    response = c.get(
        "/api/request/pypi/7",
        params={"packages": "requests==2.32.3,httpx==0.28.1"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["delivery"] == "done"
    assert len(data["packages"]) == 2
    assert all(p["in_hosted"] for p in data["packages"])


# ── npm ────────────────────────────────────────────────


async def _fake_submit_npm(*, eco, packages, requested_by):
    first = packages[0]
    pr = PullRequest(
        number=99,
        html_url="https://github.sk-inc.com/CICD/npmPackages/pull/99",
        state="open",
        merged=False,
        title=f"request: {first[0]}=={first[1]}",
        node_id="PR_99",
    )
    return pr, "request/20260101-web-lodash", True, "MERGE"


async def _fake_validate_npm(*, eco, name, version):
    return [
        {
            "key": "upstream",
            "label": "업스트림 버전 존재",
            "passed": True,
            "detail": f"npm에 {name}=={version} 확인됨.",
        },
        {
            "key": "hosted",
            "label": "Hosted에 이미 등록됨",
            "passed": True,
            "detail": "npm-hosted에 없음",
        },
        {
            "key": "inventory",
            "label": "Inventory에 이미 등록됨",
            "passed": True,
            "detail": "inventory에 없음",
        },
        {
            "key": "requests",
            "label": "요청 목록 중복 없음",
            "passed": True,
            "detail": "요청 목록에 없습니다.",
        },
    ]


def test_request_npm_success(monkeypatch):
    monkeypatch.setattr(settings, "github_token", "dummy-token")
    monkeypatch.setattr(
        "app.routers.package_request.gitops.submit_package_request", _fake_submit_npm
    )
    c = _authed()
    response = c.post(
        "/api/request/npm",
        json={"packages": [{"name": "lodash", "version": "4.17.21"}]},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["ecosystem"] == "npm"
    assert data["pr_number"] == 99
    assert data["packages"][0]["name"] == "lodash"
    assert "npmPackages" in data["repository"]


def test_request_npm_scoped(monkeypatch):
    monkeypatch.setattr(settings, "github_token", "dummy-token")
    monkeypatch.setattr(
        "app.routers.package_request.gitops.submit_package_request", _fake_submit_npm
    )
    c = _authed()
    response = c.post(
        "/api/request/npm",
        json={"packages": [{"name": "@scope/pkg", "version": "1.2.3"}]},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["ecosystem"] == "npm"
    assert data["packages"][0]["name"] == "@scope/pkg"
    assert data["packages"][0]["version"] == "1.2.3"


def test_validate_npm_success(monkeypatch):
    monkeypatch.setattr(settings, "github_token", "dummy-token")
    monkeypatch.setattr(
        "app.routers.package_request.gitops.validate_package_request",
        _fake_validate_npm,
    )
    c = _authed()
    response = c.post(
        "/api/request/npm/validate",
        json={"packages": [{"name": "@scope/pkg", "version": "1.2.3"}]},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["can_request"] is True
    assert data["items"][0]["name"] == "@scope/pkg"
    assert len(data["items"][0]["checks"]) == 5


def test_validate_npm_blocked(monkeypatch):
    async def _blocked(*, eco, name, version):
        return [
            {
                "key": "upstream",
                "label": "업스트림 버전 존재",
                "passed": False,
                "detail": f"npm에 {name}=={version}이(가) 없습니다.",
            },
            {
                "key": "hosted",
                "label": "Hosted에 이미 등록됨",
                "passed": True,
                "detail": "npm-hosted에 없음",
            },
            {
                "key": "inventory",
                "label": "Inventory에 이미 등록됨",
                "passed": True,
                "detail": "inventory에 없음",
            },
            {
                "key": "requests",
                "label": "요청 목록 중복 없음",
                "passed": True,
                "detail": "요청 목록에 없습니다.",
            },
        ]

    monkeypatch.setattr(settings, "github_token", "dummy-token")
    monkeypatch.setattr(
        "app.routers.package_request.gitops.validate_package_request",
        _blocked,
    )
    c = _authed()
    response = c.post(
        "/api/request/npm/validate",
        json={"packages": [{"name": "lodash", "version": "9.9.9"}]},
    )
    assert response.status_code == 200
    assert response.json()["can_request"] is False


def test_npm_status_delivery_pending(monkeypatch):
    async def _merge_if_ready(owner, repo, number):
        assert repo == "npmPackages"
        return PullRequest(
            number=number,
            html_url=f"https://github.sk-inc.com/CICD/npmPackages/pull/{number}",
            state="open",
            merged=False,
            title="request: lodash==4.17.21",
            node_id="PR_1",
        )

    async def _raw(owner, repo, number):
        return {"mergeable_state": "blocked"}

    monkeypatch.setattr(settings, "github_token", "dummy-token")
    monkeypatch.setattr(
        "app.routers.package_request.github.merge_if_ready", _merge_if_ready
    )
    monkeypatch.setattr("app.routers.package_request.github.get_pull_raw", _raw)
    c = _authed()
    response = c.get(
        "/api/request/npm/7",
        params={"packages": "lodash==4.17.21"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["ecosystem"] == "npm"
    assert data["delivery"] == "pending"


def test_npm_status_delivery_delivering(monkeypatch):
    async def _merge_if_ready(owner, repo, number):
        return PullRequest(
            number=number,
            html_url=f"https://github.sk-inc.com/CICD/npmPackages/pull/{number}",
            state="closed",
            merged=True,
            title="request: @scope/pkg==1.2.3",
            node_id="PR_1",
        )

    async def _raw(owner, repo, number):
        return {"mergeable_state": "unknown"}

    async def _hosted(eco, name, version):
        return False

    monkeypatch.setattr(settings, "github_token", "dummy-token")
    monkeypatch.setattr(
        "app.routers.package_request.github.merge_if_ready", _merge_if_ready
    )
    monkeypatch.setattr("app.routers.package_request.github.get_pull_raw", _raw)
    monkeypatch.setattr(
        "app.routers.package_request.gitops.hosted_has_exact", _hosted
    )
    c = _authed()
    response = c.get(
        "/api/request/npm/7",
        params={"packages": "@scope/pkg==1.2.3"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["delivery"] == "delivering"
    assert data["packages"][0]["name"] == "@scope/pkg"
    assert data["packages"][0]["in_hosted"] is False


def test_npm_status_delivery_done(monkeypatch):
    async def _merge_if_ready(owner, repo, number):
        return PullRequest(
            number=number,
            html_url=f"https://github.sk-inc.com/CICD/npmPackages/pull/{number}",
            state="closed",
            merged=True,
            title="request: lodash==4.17.21",
            node_id="PR_1",
        )

    async def _raw(owner, repo, number):
        return {"mergeable_state": "unknown"}

    async def _hosted(eco, name, version):
        return True

    monkeypatch.setattr(settings, "github_token", "dummy-token")
    monkeypatch.setattr(
        "app.routers.package_request.github.merge_if_ready", _merge_if_ready
    )
    monkeypatch.setattr("app.routers.package_request.github.get_pull_raw", _raw)
    monkeypatch.setattr(
        "app.routers.package_request.gitops.hosted_has_exact", _hosted
    )
    c = _authed()
    response = c.get(
        "/api/request/npm/7",
        params={"packages": "lodash==4.17.21,@scope/pkg==1.2.3"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["delivery"] == "done"
    assert len(data["packages"]) == 2


# ── nuget ──────────────────────────────────────────────


async def _fake_submit_nuget(*, eco, packages, requested_by):
    first = packages[0]
    pr = PullRequest(
        number=77,
        html_url="https://github.sk-inc.com/CICD/nugetPackages/pull/77",
        state="open",
        merged=False,
        title=f"request: {first[0]}=={first[1]}",
        node_id="PR_77",
    )
    return pr, "request/20260101-web-newtonsoft-json", True, "MERGE"


async def _fake_validate_nuget(*, eco, name, version):
    return [
        {
            "key": "upstream",
            "label": "업스트림 버전 존재",
            "passed": True,
            "detail": f"NuGet에 {name}=={version} 확인됨.",
        },
        {
            "key": "hosted",
            "label": "Hosted에 이미 등록됨",
            "passed": True,
            "detail": "nuget-hosted에 없음",
        },
        {
            "key": "inventory",
            "label": "Inventory에 이미 등록됨",
            "passed": True,
            "detail": "inventory에 없음",
        },
        {
            "key": "requests",
            "label": "요청 목록 중복 없음",
            "passed": True,
            "detail": "요청 목록에 없습니다.",
        },
    ]


def test_request_nuget_success(monkeypatch):
    monkeypatch.setattr(settings, "github_token", "dummy-token")
    monkeypatch.setattr(
        "app.routers.package_request.gitops.submit_package_request",
        _fake_submit_nuget,
    )
    c = _authed()
    response = c.post(
        "/api/request/nuget",
        json={"packages": [{"name": "Newtonsoft.Json", "version": "13.0.3"}]},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["ecosystem"] == "nuget"
    assert data["pr_number"] == 77
    assert data["packages"][0]["name"] == "Newtonsoft.Json"
    assert "nugetPackages" in data["repository"]


def test_validate_nuget_success(monkeypatch):
    monkeypatch.setattr(settings, "github_token", "dummy-token")
    monkeypatch.setattr(
        "app.routers.package_request.gitops.validate_package_request",
        _fake_validate_nuget,
    )
    c = _authed()
    response = c.post(
        "/api/request/nuget/validate",
        json={"packages": [{"name": "Newtonsoft.Json", "version": "13.0.3"}]},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["can_request"] is True
    assert data["items"][0]["name"] == "Newtonsoft.Json"
    assert len(data["items"][0]["checks"]) == 5


def test_nuget_status_delivery_pending(monkeypatch):
    async def _merge_if_ready(owner, repo, number):
        assert repo == "nugetPackages"
        return PullRequest(
            number=number,
            html_url=f"https://github.sk-inc.com/CICD/nugetPackages/pull/{number}",
            state="open",
            merged=False,
            title="request: Newtonsoft.Json==13.0.3",
            node_id="PR_1",
        )

    async def _raw(owner, repo, number):
        return {"mergeable_state": "blocked"}

    monkeypatch.setattr(settings, "github_token", "dummy-token")
    monkeypatch.setattr(
        "app.routers.package_request.github.merge_if_ready", _merge_if_ready
    )
    monkeypatch.setattr("app.routers.package_request.github.get_pull_raw", _raw)
    c = _authed()
    response = c.get(
        "/api/request/nuget/7",
        params={"packages": "Newtonsoft.Json==13.0.3"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["ecosystem"] == "nuget"
    assert data["delivery"] == "pending"


def test_nuget_status_delivery_done(monkeypatch):
    async def _merge_if_ready(owner, repo, number):
        return PullRequest(
            number=number,
            html_url=f"https://github.sk-inc.com/CICD/nugetPackages/pull/{number}",
            state="closed",
            merged=True,
            title="request: Newtonsoft.Json==13.0.3",
            node_id="PR_1",
        )

    async def _raw(owner, repo, number):
        return {"mergeable_state": "unknown"}

    async def _hosted(eco, name, version):
        return True

    monkeypatch.setattr(settings, "github_token", "dummy-token")
    monkeypatch.setattr(
        "app.routers.package_request.github.merge_if_ready", _merge_if_ready
    )
    monkeypatch.setattr("app.routers.package_request.github.get_pull_raw", _raw)
    monkeypatch.setattr(
        "app.routers.package_request.gitops.hosted_has_exact", _hosted
    )
    c = _authed()
    response = c.get(
        "/api/request/nuget/7",
        params={"packages": "Newtonsoft.Json==13.0.3"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["delivery"] == "done"
    assert data["packages"][0]["in_hosted"] is True
