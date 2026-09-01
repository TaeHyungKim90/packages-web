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
