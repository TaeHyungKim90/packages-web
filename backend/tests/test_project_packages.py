import pytest
from app.services.project_packages import (
    AggregatedRow,
    LockFile,
    LockPackage,
    ProjectSnapshot,
    RepoSnapshot,
    Snapshot,
    aggregate_by_package,
    attach_cve_scores,
    filter_aggregated,
    load_snapshot_cached,
    previous_lock_index,
)
from app.services.store_packages import load_snapshot, save_snapshot


def test_aggregate_joins_organizations():
    snap = Snapshot(
        projects=[
            ProjectSnapshot(
                org="AAC",
                repos=[
                    RepoSnapshot(
                        name="api",
                        lock_files=[
                            LockFile(
                                path="uv.lock",
                                format="pypi",
                                packages=[
                                    LockPackage("fastapi", "0.115.0"),
                                ],
                            )
                        ],
                    )
                ],
            ),
            ProjectSnapshot(
                org="AAP",
                repos=[
                    RepoSnapshot(
                        name="svc",
                        lock_files=[
                            LockFile(
                                path="uv.lock",
                                format="pypi",
                                packages=[
                                    LockPackage("fastapi", "0.115.0"),
                                    LockPackage("httpx", "0.27.0"),
                                ],
                            )
                        ],
                    )
                ],
            ),
        ]
    )
    rows = aggregate_by_package(snap)
    by_key = {(r.name, r.version): r for r in rows}
    assert by_key[("fastapi", "0.115.0")].organizations == ["AAC", "AAP"]
    assert by_key[("httpx", "0.27.0")].organizations == ["AAP"]


def test_filter_org_and_name():
    rows = [
        AggregatedRow(
            format="pypi",
            name="FastAPI",
            version="1",
            organizations=["AAC", "AAP"],
        ),
        AggregatedRow(
            format="npm",
            name="react",
            version="19",
            organizations=["ABD"],
        ),
    ]
    filtered = filter_aggregated(rows, org="AAC", name="fast")
    assert len(filtered) == 1
    assert filtered[0].name == "FastAPI"


def test_attach_cve_scores_uses_normalized_name():
    rows = [
        AggregatedRow(format="pypi", name="Requests", version="2.28.0"),
    ]
    attach_cve_scores(rows, {("pypi", "requests", "2.28.0"): 7.5})
    assert rows[0].max_threat_level == 7.5


def test_save_load_snapshot_roundtrip():
    snap = Snapshot(
        collected_at="2026-01-01T00:00:00+00:00",
        projects=[
            ProjectSnapshot(
                org="AAC",
                repos=[
                    RepoSnapshot(
                        name="api",
                        lock_files=[
                            LockFile(
                                path="uv.lock",
                                format="pypi",
                                sha="abc",
                                packages=[LockPackage("fastapi", "0.115.0")],
                            )
                        ],
                    )
                ],
            )
        ],
        aggregated=[
            AggregatedRow(
                format="pypi",
                name="fastapi",
                version="0.115.0",
                imported_at="2026-08-16T00:00:00+00:00",
                max_threat_level=8.6,
                organizations=["AAC"],
            )
        ],
    )
    save_snapshot(snap)
    loaded = load_snapshot()
    from app.services.project_packages import invalidate_snapshot_cache

    invalidate_snapshot_cache()
    assert load_snapshot_cached().projects[0].repos[0].lock_files[0].sha == "abc"
    assert loaded.aggregated[0].max_threat_level == 8.6


def test_previous_lock_index_for_sha_skip():
    prev = LockFile(path="uv.lock", format="pypi", sha="same", packages=[])
    snap = Snapshot(
        projects=[
            ProjectSnapshot(
                org="AAC",
                repos=[RepoSnapshot(name="api", lock_files=[prev])],
            )
        ]
    )
    index = previous_lock_index(snap)
    assert index[("AAC", "api", "uv.lock")].sha == "same"


@pytest.mark.asyncio
async def test_fetch_lock_skips_parse_when_sha_matches(monkeypatch):
    import asyncio

    from app.services.github import RepoFile
    from app.services.project_packages import _fetch_lock

    async def _get(*_a, **_k):
        return RepoFile(path="uv.lock", content="invalid toml {{{", sha="same")

    monkeypatch.setattr("app.services.project_packages.github.get_file", _get)
    prev = LockFile(
        path="uv.lock",
        format="pypi",
        sha="same",
        packages=[LockPackage("cached", "1.0")],
    )
    result = await _fetch_lock(
        "AAC", "api", "uv.lock", "pypi", prev, asyncio.Semaphore(1)
    )
    assert result is prev
    assert result.packages[0].name == "cached"


def test_is_dotnet_repo():
    from app.services.project_packages import is_dotnet_repo

    assert is_dotnet_repo("AIP_APP_DOTNET") is True
    assert is_dotnet_repo("aip-app-dotnet-svc") is True
    assert is_dotnet_repo("AIP_AGENT_BACKEND_PYTHON") is False


@pytest.mark.asyncio
async def test_collect_org_scans_nuget_only_on_dotnet_repos(monkeypatch):
    import asyncio

    from app.services.ghes_models import StoredOrg, StoredRepo
    from app.services.github import RepoFile
    from app.services.project_packages import collect_org

    listed: list[str] = []

    async def _list_paths(org, repo, *, ref, filename):
        listed.append(repo)
        assert filename == "packages.lock.json"
        if repo == "AIP_APP_DOTNET":
            return ["src/App/packages.lock.json"]
        return []

    async def _get(org, repo, path, *, ref):
        if path.endswith("packages.lock.json"):
            return RepoFile(
                path=path,
                content='{"dependencies":{"net8.0":{"Newtonsoft.Json":{"type":"Direct","resolved":"13.0.3"}}}}',
                sha="n1",
            )
        return None

    monkeypatch.setattr(
        "app.services.project_packages.github.list_paths_named", _list_paths
    )
    monkeypatch.setattr("app.services.project_packages.github.get_file", _get)

    org = StoredOrg(
        name="AIP",
        managed=True,
        repos=[
            StoredRepo(name="AIP_APP_DOTNET"),
            StoredRepo(name="AIP_AGENT_BACKEND_PYTHON"),
        ],
    )
    snap = await collect_org(
        org, previous=Snapshot(), sem=asyncio.Semaphore(5)
    )
    assert listed == ["AIP_APP_DOTNET"]
    by_repo = {r.name: r for r in snap.repos}
    nuget_locks = [
        lf for lf in by_repo["AIP_APP_DOTNET"].lock_files if lf.format == "nuget"
    ]
    assert len(nuget_locks) == 1
    assert nuget_locks[0].path == "src/App/packages.lock.json"
    assert nuget_locks[0].packages[0].name == "Newtonsoft.Json"
    assert not any(lf.format == "nuget" for lf in by_repo["AIP_AGENT_BACKEND_PYTHON"].lock_files)


def _ts(day: int):
    from datetime import UTC, datetime

    return datetime(2026, 9, day, tzinfo=UTC)


def test_select_latest_locks_keeps_newest_in_same_dir():
    from app.services.project_packages import select_latest_locks

    old = LockFile(path="frontend/package-lock.json", format="npm")
    new = LockFile(path="frontend/pnpm-lock.yaml", format="npm")
    root = LockFile(path="package-lock.json", format="npm")
    uv = LockFile(path="frontend/uv.lock", format="pypi")
    kept = select_latest_locks(
        [old, new, root, uv],
        {old.path: _ts(1), new.path: _ts(20)},
    )
    assert [lf.path for lf in kept] == [
        "frontend/pnpm-lock.yaml",
        "package-lock.json",
        "frontend/uv.lock",
    ]


def test_select_latest_locks_undated_loses_to_dated():
    from app.services.project_packages import select_latest_locks

    dated = LockFile(path="yarn.lock", format="npm")
    undated = LockFile(path="package-lock.json", format="npm")
    kept = select_latest_locks([undated, dated], {dated.path: _ts(1), undated.path: None})
    assert [lf.path for lf in kept] == ["yarn.lock"]


def test_select_latest_locks_keeps_all_when_no_times():
    from app.services.project_packages import select_latest_locks

    a = LockFile(path="package-lock.json", format="npm")
    b = LockFile(path="yarn.lock", format="npm")
    kept = select_latest_locks([a, b], {})
    assert [lf.path for lf in kept] == ["package-lock.json", "yarn.lock"]


def test_select_latest_locks_tie_uses_first_path():
    from app.services.project_packages import select_latest_locks

    a = LockFile(path="yarn.lock", format="npm")
    b = LockFile(path="package-lock.json", format="npm")
    kept = select_latest_locks([a, b], {a.path: _ts(5), b.path: _ts(5)})
    assert [lf.path for lf in kept] == ["package-lock.json"]


@pytest.mark.asyncio
async def test_collect_org_uses_latest_npm_lock_per_dir(monkeypatch):
    import asyncio

    from app.services.ghes_models import StoredOrg, StoredRepo
    from app.services.github import RepoFile
    from app.services.project_packages import collect_org

    package_lock = (
        '{"lockfileVersion":3,"packages":{"":{},'
        '"node_modules/left-pad":{"version":"1.0.0"}}}'
    )
    pnpm_lock = "lockfileVersion: '9.0'\npackages:\n  left-pad@1.3.0:\n    resolution: {}\n"
    files = {
        "frontend/package-lock.json": package_lock,
        "frontend/pnpm-lock.yaml": pnpm_lock,
        "package-lock.json": package_lock,
    }
    commit_days = {"frontend/package-lock.json": 1, "frontend/pnpm-lock.yaml": 20}
    looked_up: list[str] = []

    async def _get(org, repo, path, *, ref):
        if path in files:
            return RepoFile(path=path, content=files[path], sha=path)
        return None

    async def _commit_at(org, repo, path, *, ref):
        looked_up.append(path)
        return _ts(commit_days[path])

    monkeypatch.setattr("app.services.project_packages.github.get_file", _get)
    monkeypatch.setattr(
        "app.services.project_packages.github.latest_commit_at", _commit_at
    )

    org = StoredOrg(name="AAC", managed=True, repos=[StoredRepo(name="web")])
    snap = await collect_org(org, previous=Snapshot(), sem=asyncio.Semaphore(5))

    repo = snap.repos[0]
    assert sorted(lf.path for lf in repo.lock_files) == [
        "frontend/pnpm-lock.yaml",
        "package-lock.json",
    ]
    pnpm = next(lf for lf in repo.lock_files if lf.path == "frontend/pnpm-lock.yaml")
    assert [(p.name, p.version) for p in pnpm.packages] == [("left-pad", "1.3.0")]
    assert sorted(looked_up) == ["frontend/package-lock.json", "frontend/pnpm-lock.yaml"]
    assert repo.errors == []


@pytest.mark.asyncio
async def test_collect_org_keeps_all_locks_when_commit_lookup_fails(monkeypatch):
    import asyncio

    from app.services.ghes_models import StoredOrg, StoredRepo
    from app.services.github import GitHubError, RepoFile
    from app.services.project_packages import collect_org

    package_lock = '{"lockfileVersion":3,"packages":{"node_modules/a":{"version":"1.0.0"}}}'
    yarn_lock = 'a@^1.0.0:\n  version "1.1.0"\n'
    files = {"package-lock.json": package_lock, "yarn.lock": yarn_lock}

    async def _get(org, repo, path, *, ref):
        if path in files:
            return RepoFile(path=path, content=files[path], sha=path)
        return None

    async def _commit_at(org, repo, path, *, ref):
        raise GitHubError("boom", status_code=502)

    monkeypatch.setattr("app.services.project_packages.github.get_file", _get)
    monkeypatch.setattr(
        "app.services.project_packages.github.latest_commit_at", _commit_at
    )

    org = StoredOrg(name="AAC", managed=True, repos=[StoredRepo(name="web")])
    snap = await collect_org(org, previous=Snapshot(), sem=asyncio.Semaphore(5))

    repo = snap.repos[0]
    assert sorted(lf.path for lf in repo.lock_files) == ["package-lock.json", "yarn.lock"]
    assert any("cannot determine latest lockfile" in e for e in repo.errors)


def test_rebuild_vuln_index_skips_already_fixed_versions():
    from app.db import connect, init_schema
    from app.schemas import ProxyHealthResponse, ProxyHealthVulnerability
    from app.services.proxy_health_store import save_proxy_health_to_conn
    from app.services.store_packages import rebuild_vulnerability_index_from_proxy_health

    conn = connect()
    init_schema(conn)
    save_proxy_health_to_conn(
        conn,
        ProxyHealthResponse(
            ecosystem="pypi",
            repository="pypi-proxy-health",
            generated_at="2026-01-01T00:00:00+00:00",
            vulnerabilities=[
                ProxyHealthVulnerability(
                    threat_level=9.0,
                    problem_code="CVE-FIXED",
                    artifact="foo",
                    version="1.2.0",
                    fixed_version="1.2.0",
                ),
                ProxyHealthVulnerability(
                    threat_level=8.0,
                    problem_code="CVE-PAST-FIX",
                    artifact="bar",
                    version="2.1.0",
                    fixed_version="2.0.0",
                ),
                ProxyHealthVulnerability(
                    threat_level=7.5,
                    problem_code="CVE-OPEN",
                    artifact="baz",
                    version="1.0.0",
                    fixed_version="1.2.0",
                ),
                ProxyHealthVulnerability(
                    threat_level=6.0,
                    problem_code="CVE-NO-FIX",
                    artifact="qux",
                    version="0.1.0",
                    fixed_version=None,
                ),
            ],
            licenses=[],
        ),
    )
    conn.commit()
    index = rebuild_vulnerability_index_from_proxy_health(conn)
    conn.commit()
    conn.close()

    assert ("pypi", "foo", "1.2.0") not in index
    assert ("pypi", "bar", "2.1.0") not in index
    assert index[("pypi", "baz", "1.0.0")] == 7.5
    assert index[("pypi", "qux", "0.1.0")] == 6.0


def test_rebuild_vuln_index_respects_override_fixed_version():
    from app.db import connect, init_schema
    from app.schemas import (
        ProxyHealthResponse,
        ProxyHealthVulnerability,
        ProxyHealthVulnOverrideUpdate,
    )
    from app.services.proxy_health_store import (
        save_proxy_health_to_conn,
        save_vuln_override,
    )
    from app.services.store_packages import rebuild_vulnerability_index_from_proxy_health

    conn = connect()
    init_schema(conn)
    save_proxy_health_to_conn(
        conn,
        ProxyHealthResponse(
            ecosystem="pypi",
            repository="pypi-proxy-health",
            generated_at="2026-01-01T00:00:00+00:00",
            vulnerabilities=[
                ProxyHealthVulnerability(
                    threat_level=9.0,
                    problem_code="CVE-1",
                    artifact="pkg",
                    version="1.0.0",
                    fixed_version=None,
                ),
            ],
            licenses=[],
        ),
    )
    save_vuln_override(
        conn,
        "pypi",
        ProxyHealthVulnOverrideUpdate(
            problem_code="CVE-1",
            artifact="pkg",
            fixed_version="1.0.0",
            remark="already fixed",
        ),
    )
    conn.commit()
    index = rebuild_vulnerability_index_from_proxy_health(conn)
    conn.close()
    assert ("pypi", "pkg", "1.0.0") not in index


def test_rebuild_vuln_index_skips_false_positive_remark():
    from app.db import connect, init_schema
    from app.schemas import (
        ProxyHealthResponse,
        ProxyHealthVulnerability,
        ProxyHealthVulnOverrideUpdate,
    )
    from app.services.proxy_health_store import (
        save_proxy_health_to_conn,
        save_vuln_override,
    )
    from app.services.store_packages import rebuild_vulnerability_index_from_proxy_health

    conn = connect()
    init_schema(conn)
    save_proxy_health_to_conn(
        conn,
        ProxyHealthResponse(
            ecosystem="pypi",
            repository="pypi-proxy-health",
            generated_at="2026-01-01T00:00:00+00:00",
            vulnerabilities=[
                ProxyHealthVulnerability(
                    threat_level=9.0,
                    problem_code="CVE-FP",
                    artifact="noise",
                    version="1.0.0",
                    fixed_version=None,
                ),
            ],
            licenses=[],
        ),
    )
    save_vuln_override(
        conn,
        "pypi",
        ProxyHealthVulnOverrideUpdate(
            problem_code="CVE-FP",
            artifact="noise",
            fixed_version=None,
            remark="오탐",
        ),
    )
    conn.commit()
    index = rebuild_vulnerability_index_from_proxy_health(conn)
    conn.close()
    assert ("pypi", "noise", "1.0.0") not in index
