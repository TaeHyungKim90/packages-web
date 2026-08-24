from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import yaml

from app.config import ECOSYSTEM_MAP, settings
from app.services import ghes_inventory, github
from app.services.github import GitHubError
from app.services.lock_parsers import parse_lock
from app.services.nexus import blob_created_map, import_name_key
from app.services.nexus_health import fetch_proxy_health

GHES_CONCURRENCY = 5
LOCK_CANDIDATES: list[tuple[str, str]] = [
    ("pypi", "uv.lock"),
    ("pypi", "backend/uv.lock"),
    ("pypi", "frontend/uv.lock"),
    ("npm", "package-lock.json"),
    ("npm", "backend/package-lock.json"),
    ("npm", "frontend/package-lock.json"),
    ("nuget", "packages.lock.json"),
    ("nuget", "src/packages.lock.json"),
    ("nuget", "backend/packages.lock.json"),
    ("nuget", "frontend/packages.lock.json"),
]


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


_snapshot_cache: tuple[float, Snapshot] | None = None


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def resolve_packages_yaml() -> Path:
    configured = (settings.ghes_project_packages_yaml_path or "").strip()
    if configured:
        return Path(configured)
    return _repo_root() / "config" / "ghes-project-packages.yaml"


def resolve_vulnerabilities_yaml() -> Path:
    configured = (settings.ghes_package_vulnerabilities_yaml_path or "").strip()
    if configured:
        return Path(configured)
    return _repo_root() / "config" / "ghes-package-vulnerabilities.yaml"


def list_managed_projects() -> list[ghes_inventory.StoredOrg]:
    return [org for org in ghes_inventory.load_yaml() if org.managed]


def _parse_lock_file(raw: Any) -> LockFile | None:
    if not isinstance(raw, dict):
        return None
    path = str(raw.get("path") or "").strip()
    fmt = str(raw.get("format") or "").strip().lower()
    if not path or fmt not in {"pypi", "npm", "nuget"}:
        return None
    packages: list[LockPackage] = []
    for item in raw.get("packages") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        version = str(item.get("version") or "").strip()
        if name and version:
            packages.append(LockPackage(name=name, version=version))
    return LockFile(
        path=path,
        format=fmt,
        sha=str(raw.get("sha") or ""),
        packages=packages,
    )


def _parse_aggregated(raw: Any) -> AggregatedRow | None:
    if not isinstance(raw, dict):
        return None
    fmt = str(raw.get("format") or "").strip().lower()
    name = str(raw.get("name") or "").strip()
    version = str(raw.get("version") or "").strip()
    if fmt not in {"pypi", "npm", "nuget"} or not name or not version:
        return None
    orgs = [
        str(o).strip()
        for o in (raw.get("organizations") or [])
        if str(o).strip()
    ]
    threat = raw.get("max_threat_level")
    threat_val: float | None
    try:
        threat_val = float(threat) if threat is not None else None
    except (TypeError, ValueError):
        threat_val = None
    imported = raw.get("imported_at")
    return AggregatedRow(
        format=fmt,
        name=name,
        version=version,
        imported_at=str(imported) if imported else None,
        max_threat_level=threat_val,
        organizations=orgs,
    )


def load_snapshot(path: Path | None = None) -> Snapshot:
    target = path or resolve_packages_yaml()
    if not target.is_file():
        return Snapshot()
    raw = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        return Snapshot()
    projects: list[ProjectSnapshot] = []
    for proj in raw.get("projects") or []:
        if not isinstance(proj, dict):
            continue
        org = str(proj.get("org") or "").strip()
        if not org:
            continue
        repos: list[RepoSnapshot] = []
        for repo in proj.get("repos") or []:
            if not isinstance(repo, dict):
                continue
            name = str(repo.get("name") or "").strip()
            if not name:
                continue
            locks = [
                lf
                for item in (repo.get("lock_files") or [])
                if (lf := _parse_lock_file(item)) is not None
            ]
            errors = [str(e) for e in (repo.get("errors") or []) if e]
            repos.append(RepoSnapshot(name=name, lock_files=locks, errors=errors))
        projects.append(ProjectSnapshot(org=org, repos=repos))
    aggregated = [
        row
        for item in (raw.get("aggregated") or [])
        if (row := _parse_aggregated(item)) is not None
    ]
    return Snapshot(
        collected_at=str(raw.get("collected_at") or "") or None,
        projects=projects,
        aggregated=aggregated,
    )


def load_snapshot_cached() -> Snapshot:
    global _snapshot_cache
    path = resolve_packages_yaml()
    mtime = path.stat().st_mtime if path.is_file() else 0.0
    if _snapshot_cache and _snapshot_cache[0] == mtime:
        return _snapshot_cache[1]
    snap = load_snapshot(path)
    _snapshot_cache = (mtime, snap)
    return snap


def invalidate_snapshot_cache() -> None:
    global _snapshot_cache
    _snapshot_cache = None


def _dump_snapshot(snap: Snapshot) -> dict[str, Any]:
    return {
        "collected_at": snap.collected_at,
        "projects": [
            {
                "org": p.org,
                "repos": [
                    {
                        "name": r.name,
                        "lock_files": [
                            {
                                "path": lf.path,
                                "format": lf.format,
                                "sha": lf.sha,
                                "packages": [
                                    {"name": pkg.name, "version": pkg.version}
                                    for pkg in lf.packages
                                ],
                            }
                            for lf in r.lock_files
                        ],
                        "errors": r.errors,
                    }
                    for r in p.repos
                ],
            }
            for p in snap.projects
        ],
        "aggregated": [
            {
                "format": row.format,
                "name": row.name,
                "version": row.version,
                "imported_at": row.imported_at,
                "max_threat_level": row.max_threat_level,
                "organizations": row.organizations,
            }
            for row in snap.aggregated
        ],
    }


def save_snapshot(snap: Snapshot, path: Path | None = None) -> None:
    target = path or resolve_packages_yaml()
    target.parent.mkdir(parents=True, exist_ok=True)
    header = (
        "# GHES lock 파일 수집 스냅샷 (POST /api/project-packages/sync)\n"
        "# aggregated: GET 목록용 캐시 (imported_at, max_threat_level)\n\n"
    )
    body = yaml.safe_dump(_dump_snapshot(snap), sort_keys=False, allow_unicode=True)
    target.write_text(header + body, encoding="utf-8")
    invalidate_snapshot_cache()


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
        LockPackage(name=n, version=v) for n, v in parse_lock(fmt, file.content)
    ]
    return LockFile(path=path, format=fmt, sha=file.sha, packages=packages)


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
        tasks = [
            _fetch_lock(
                org.name,
                repo.name,
                path,
                fmt,
                prev_index.get((org.name, repo.name, path)),
                sem,
            )
            for fmt, path in LOCK_CANDIDATES
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        locks: list[LockFile] = []
        for item, (_fmt, path) in zip(results, LOCK_CANDIDATES, strict=True):
            if isinstance(item, Exception):
                errors.append(f"{path}: {item}")
                continue
            if item is not None:
                locks.append(item)
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


def load_vulnerability_index(path: Path | None = None) -> dict[tuple[str, str, str], float]:
    target = path or resolve_vulnerabilities_yaml()
    if not target.is_file():
        return {}
    raw = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        return {}
    index: dict[tuple[str, str, str], float] = {}
    for item in raw.get("entries") or []:
        if not isinstance(item, dict):
            continue
        fmt = str(item.get("format") or "").strip().lower()
        name = str(item.get("name") or "").strip()
        version = str(item.get("version") or "").strip()
        try:
            score = float(item.get("max_threat_level"))
        except (TypeError, ValueError):
            continue
        if fmt and name and version:
            index[(fmt, import_name_key(name, fmt), version)] = score
    return index


def save_vulnerability_index(
    index: dict[tuple[str, str, str], float], path: Path | None = None
) -> None:
    target = path or resolve_vulnerabilities_yaml()
    target.parent.mkdir(parents=True, exist_ok=True)
    entries = [
        {
            "format": fmt,
            "name": name,
            "version": version,
            "max_threat_level": score,
        }
        for (fmt, name, version), score in sorted(index.items())
    ]
    payload = {
        "collected_at": datetime.now(tz=UTC).isoformat(),
        "entries": entries,
    }
    header = (
        "# Nexus proxy-health security.json 인덱스 (POST /api/project-packages/sync)\n\n"
    )
    target.write_text(
        header + yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def attach_cve_scores(
    rows: list[AggregatedRow],
    index: dict[tuple[str, str, str], float] | None = None,
) -> None:
    lookup = index if index is not None else load_vulnerability_index()
    for row in rows:
        key = (row.format, import_name_key(row.name, row.format), row.version)
        row.max_threat_level = lookup.get(key)


async def build_vulnerability_index() -> dict[tuple[str, str, str], float]:
    index: dict[tuple[str, str, str], float] = {}
    for fmt in ("pypi", "npm", "nuget"):
        try:
            report = await fetch_proxy_health(fmt)
        except Exception:
            continue
        for item in report.vulnerabilities:
            if item.threat_level is None or not item.artifact or not item.version:
                continue
            key = (
                fmt,
                import_name_key(item.artifact, fmt),
                item.version,
            )
            prev = index.get(key)
            if prev is None or item.threat_level > prev:
                index[key] = float(item.threat_level)
    save_vulnerability_index(index)
    return index


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
            mapped = await blob_created_map(
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


async def sync(org_filter: str | None = None) -> Snapshot:
    snap = await collect_projects(org_filter)
    rows = aggregate_by_package(snap)
    await attach_imported_at(rows)
    vuln_index = await build_vulnerability_index()
    attach_cve_scores(rows, vuln_index)
    snap.aggregated = rows
    save_snapshot(snap)
    return snap
