from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime

import httpx

from app.config import ECOSYSTEM_MAP, settings
from app.db import connect
from app.services import ghes_inventory, github
from app.services.github import GitHubError
from app.services.lock_parsers import parse_lock
from app.services.nexus import blob_created_map, import_name_key
from app.services.proxy_health_store import ensure_all_proxy_health_cached
from app.services.store_packages import (
    load_snapshot,
    load_vulnerability_index,
    rebuild_vulnerability_index_from_proxy_health,
    save_snapshot,
)

GHES_CONCURRENCY = 5
# pypi / npm: fixed candidate paths. nuget: recursive search on *dotnet* repos only.
_NPM_LOCK_NAMES = ("package-lock.json", "pnpm-lock.yaml", "yarn.lock")
_LOCK_DIRS = ("", "backend/", "frontend/")
LOCK_CANDIDATES: list[tuple[str, str]] = [
    ("pypi", "uv.lock"),
    ("pypi", "backend/uv.lock"),
    ("pypi", "frontend/uv.lock"),
    *[
        ("npm", f"{directory}{name}")
        for name in _NPM_LOCK_NAMES
        for directory in _LOCK_DIRS
    ],
]
NUGET_LOCK_FILENAME = "packages.lock.json"


def is_dotnet_repo(repo_name: str) -> bool:
    return "dotnet" in (repo_name or "").lower()


@dataclass
class LockPackage:
    name: str
    version: str


@dataclass
class LockFile:
    path: str
    format: str
    sha: str = ""
    packages: list[LockPackage] = field(default_factory=list)


@dataclass
class RepoSnapshot:
    name: str
    lock_files: list[LockFile] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass
class ProjectSnapshot:
    org: str
    repos: list[RepoSnapshot] = field(default_factory=list)


@dataclass
class AggregatedRow:
    format: str
    name: str
    version: str
    imported_at: str | None = None
    max_threat_level: float | None = None
    organizations: list[str] = field(default_factory=list)


@dataclass
class Snapshot:
    collected_at: str | None = None
    projects: list[ProjectSnapshot] = field(default_factory=list)
    aggregated: list[AggregatedRow] = field(default_factory=list)


_snapshot_cache: Snapshot | None = None


def list_managed_projects() -> list[ghes_inventory.StoredOrg]:
    return [org for org in ghes_inventory.load_yaml() if org.managed]


def load_snapshot_cached() -> Snapshot:
    global _snapshot_cache
    if _snapshot_cache is not None:
        return _snapshot_cache
    snap = load_snapshot()
    _snapshot_cache = snap
    return snap


def invalidate_snapshot_cache() -> None:
    global _snapshot_cache
    _snapshot_cache = None


def previous_lock_index(snap: Snapshot) -> dict[tuple[str, str, str], LockFile]:
    index: dict[tuple[str, str, str], LockFile] = {}
    for proj in snap.projects:
        for repo in proj.repos:
            for lf in repo.lock_files:
                index[(proj.org, repo.name, lf.path)] = lf
    return index


async def _fetch_lock(
    org: str,
    repo: str,
    path: str,
    fmt: str,
    prev: LockFile | None,
    sem: asyncio.Semaphore,
) -> LockFile | None:
    async with sem:
        try:
            file = await github.get_file(
                org, repo, path, ref=settings.github_base_branch
            )
        except GitHubError as exc:
            raise GitHubError(
                f"{org}/{repo}/{path}: {exc}", status_code=exc.status_code
            ) from exc
    if file is None:
        return None
    if prev is not None and prev.sha and prev.sha == file.sha:
        return prev
    packages = [
        LockPackage(name=n, version=v)
        for n, v in parse_lock(fmt, file.content, path=path)
    ]
    return LockFile(path=path, format=fmt, sha=file.sha, packages=packages)


def lock_group_key(lock: LockFile) -> tuple[str, str]:
    """Same directory + same format = alternative lockfiles for one project."""
    directory = lock.path.rsplit("/", 1)[0] if "/" in lock.path else ""
    return directory, lock.format


def select_latest_locks(
    locks: list[LockFile],
    committed_at: dict[str, datetime | None],
) -> list[LockFile]:
    """Keep only the most recently committed lockfile per (directory, format).

    Files without a commit time lose to files with one; if no file in a group has
    a time, the whole group is kept. Ties go to the lexicographically first path.
    """
    groups: dict[tuple[str, str], list[LockFile]] = {}
    for lock in locks:
        groups.setdefault(lock_group_key(lock), []).append(lock)

    dropped: set[int] = set()
    for members in groups.values():
        if len(members) < 2:
            continue
        dated = [m for m in members if committed_at.get(m.path) is not None]
        if not dated:
            continue
        winner = min(dated, key=lambda m: (-committed_at[m.path].timestamp(), m.path))
        dropped.update(id(m) for m in members if m is not winner)
    return [lock for lock in locks if id(lock) not in dropped]


async def _keep_latest_locks(
    org: str,
    repo: str,
    locks: list[LockFile],
    sem: asyncio.Semaphore,
) -> tuple[list[LockFile], list[str]]:
    groups: dict[tuple[str, str], list[LockFile]] = {}
    for lock in locks:
        groups.setdefault(lock_group_key(lock), []).append(lock)
    contested = [m for members in groups.values() if len(members) > 1 for m in members]
    if not contested:
        return locks, []

    async def commit_time(path: str) -> datetime | None:
        async with sem:
            return await github.latest_commit_at(
                org, repo, path, ref=settings.github_base_branch
            )

    results = await asyncio.gather(
        *(commit_time(m.path) for m in contested), return_exceptions=True
    )
    errors: list[str] = []
    committed_at: dict[str, datetime | None] = {}
    for lock, result in zip(contested, results, strict=True):
        if isinstance(result, Exception):
            errors.append(f"{lock.path}: commit time lookup failed: {result}")
            committed_at[lock.path] = None
        else:
            committed_at[lock.path] = result

    for (directory, fmt), members in groups.items():
        if len(members) > 1 and all(committed_at.get(m.path) is None for m in members):
            paths = ", ".join(m.path for m in members)
            errors.append(
                f"{directory or '.'} ({fmt}): cannot determine latest lockfile, using all: {paths}"
            )
    return select_latest_locks(locks, committed_at), errors


async def collect_org(
    org: ghes_inventory.StoredOrg,
    *,
    previous: Snapshot,
    sem: asyncio.Semaphore,
) -> ProjectSnapshot:
    prev_index = previous_lock_index(previous)
    repos: list[RepoSnapshot] = []
    for repo in org.repos:
        errors: list[str] = []
        candidates = list(LOCK_CANDIDATES)
        if is_dotnet_repo(repo.name):
            try:
                nuget_paths = await github.list_paths_named(
                    org.name,
                    repo.name,
                    ref=settings.github_base_branch,
                    filename=NUGET_LOCK_FILENAME,
                )
            except GitHubError as exc:
                errors.append(f"{NUGET_LOCK_FILENAME} scan: {exc}")
                nuget_paths = []
            for path in nuget_paths:
                candidates.append(("nuget", path))

        tasks = [
            _fetch_lock(
                org.name,
                repo.name,
                path,
                fmt,
                prev_index.get((org.name, repo.name, path)),
                sem,
            )
            for fmt, path in candidates
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        locks: list[LockFile] = []
        for item, (_fmt, path) in zip(results, candidates, strict=True):
            if isinstance(item, Exception):
                errors.append(f"{path}: {item}")
                continue
            if item is not None:
                locks.append(item)
        locks, lock_errors = await _keep_latest_locks(org.name, repo.name, locks, sem)
        errors.extend(lock_errors)
        repos.append(RepoSnapshot(name=repo.name, lock_files=locks, errors=errors))
    return ProjectSnapshot(org=org.name, repos=repos)


async def collect_projects(org_filter: str | None = None) -> Snapshot:
    managed = list_managed_projects()
    if org_filter:
        key = org_filter.strip()
        managed = [o for o in managed if o.name == key]
        if not managed:
            raise ValueError(f"managed organization not found: {org_filter}")
    previous = load_snapshot()
    sem = asyncio.Semaphore(GHES_CONCURRENCY)
    projects = await asyncio.gather(
        *(collect_org(org, previous=previous, sem=sem) for org in managed)
    )
    if org_filter:
        by_org = {p.org: p for p in previous.projects}
        for proj in projects:
            by_org[proj.org] = proj
        merged = [by_org[name] for name in sorted(by_org, key=str.lower)]
    else:
        merged = list(projects)
    return Snapshot(
        collected_at=datetime.now(tz=UTC).isoformat(),
        projects=merged,
    )


def aggregate_by_package(snap: Snapshot) -> list[AggregatedRow]:
    grouped: dict[tuple[str, str, str], set[str]] = {}
    for proj in snap.projects:
        for repo in proj.repos:
            for lf in repo.lock_files:
                for pkg in lf.packages:
                    key = (lf.format, pkg.name, pkg.version)
                    grouped.setdefault(key, set()).add(proj.org)
    rows = [
        AggregatedRow(
            format=fmt,
            name=name,
            version=version,
            organizations=sorted(orgs, key=str.lower),
        )
        for (fmt, name, version), orgs in grouped.items()
    ]
    rows.sort(key=lambda r: (r.format, r.name.lower(), r.version))
    return rows


def attach_cve_scores(
    rows: list[AggregatedRow],
    index: dict[tuple[str, str, str], float] | None = None,
) -> None:
    lookup = index if index is not None else load_vulnerability_index()
    for row in rows:
        key = (row.format, import_name_key(row.name, row.format), row.version)
        row.max_threat_level = lookup.get(key)


async def build_vulnerability_index() -> dict[tuple[str, str, str], float]:
    await ensure_all_proxy_health_cached()
    conn = connect()
    try:
        return rebuild_vulnerability_index_from_proxy_health(conn)
    finally:
        conn.commit()
        conn.close()


async def attach_imported_at(rows: list[AggregatedRow]) -> None:
    by_fmt: dict[str, set[tuple[str, str]]] = {}
    for row in rows:
        by_fmt.setdefault(row.format, set()).add((row.name, row.version))
    dates: dict[tuple[str, str, str], str] = {}
    async with httpx.AsyncClient(verify=settings.nexus_verify_ssl) as client:
        for fmt, keys in by_fmt.items():
            eco = ECOSYSTEM_MAP.get(fmt)
            if not eco:
                continue
            mapped, _hosted_keys = await blob_created_map(
                client,
                hosted_repo=eco.hosted_repo,
                health_repo=eco.health_repo,
                package_format=fmt,
                keys=keys,
            )
            for (name, version), stamp in mapped.items():
                dates[(fmt, name, version)] = stamp
    for row in rows:
        key = (
            row.format,
            import_name_key(row.name, row.format),
            row.version,
        )
        row.imported_at = dates.get(key)


def filter_aggregated(
    rows: list[AggregatedRow],
    *,
    org: str | None = None,
    name: str | None = None,
    format: str | None = None,
) -> list[AggregatedRow]:
    org_key = (org or "").strip()
    name_key = (name or "").strip().lower()
    fmt_key = (format or "").strip().lower()
    out: list[AggregatedRow] = []
    for row in rows:
        if org_key and org_key not in row.organizations:
            continue
        if fmt_key and row.format != fmt_key:
            continue
        if name_key and name_key not in row.name.lower():
            continue
        out.append(row)
    return out


def _persist_snapshot(snap: Snapshot) -> None:
    save_snapshot(snap)
    invalidate_snapshot_cache()


async def sync(org_filter: str | None = None) -> Snapshot:
    snap = await collect_projects(org_filter)
    rows = aggregate_by_package(snap)
    await attach_imported_at(rows)
    vuln_index = await build_vulnerability_index()
    attach_cve_scores(rows, vuln_index)
    snap.aggregated = rows
    _persist_snapshot(snap)
    return snap
