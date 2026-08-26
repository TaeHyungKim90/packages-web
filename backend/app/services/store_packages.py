from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from app.db import connect
from app.services.nexus import import_name_key


def _parse_lock_file(raw: Any):
    from app.services.project_packages import LockFile, LockPackage

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


def _parse_aggregated(raw: Any):
    from app.services.project_packages import AggregatedRow

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


def snapshot_from_yaml_dict(raw: dict[str, Any]):
    from app.services.project_packages import (
        ProjectSnapshot,
        RepoSnapshot,
        Snapshot,
    )

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


def import_snapshot_yaml(conn: sqlite3.Connection, path: Path) -> None:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        return
    snap = snapshot_from_yaml_dict(raw)
    save_snapshot_to_conn(conn, snap)


def load_snapshot_from_conn(conn: sqlite3.Connection):
    from app.services.project_packages import (
        AggregatedRow,
        LockFile,
        LockPackage,
        ProjectSnapshot,
        RepoSnapshot,
        Snapshot,
    )

    meta = conn.execute(
        "SELECT collected_at FROM package_snapshot_meta WHERE id = 1"
    ).fetchone()
    collected_at = meta["collected_at"] if meta else None

    org_names = [
        r["org"]
        for r in conn.execute(
            "SELECT DISTINCT org FROM lock_file "
            "UNION SELECT DISTINCT org FROM repo_error "
            "ORDER BY org COLLATE NOCASE"
        )
    ]
    projects_list: list[ProjectSnapshot] = []
    for org in org_names:
        repo_names = [
            r["repo"]
            for r in conn.execute(
                "SELECT DISTINCT repo FROM lock_file WHERE org = ? "
                "UNION SELECT DISTINCT repo FROM repo_error WHERE org = ? "
                "ORDER BY repo COLLATE NOCASE",
                (org, org),
            )
        ]
        repos: list[RepoSnapshot] = []
        for repo in repo_names:
            locks: list[LockFile] = []
            for lf in conn.execute(
                "SELECT path, format, sha FROM lock_file "
                "WHERE org = ? AND repo = ? ORDER BY path",
                (org, repo),
            ):
                packages = [
                    LockPackage(name=r["name"], version=r["version"])
                    for r in conn.execute(
                        "SELECT name, version FROM lock_package "
                        "WHERE org = ? AND repo = ? AND lock_path = ? "
                        "ORDER BY name COLLATE NOCASE",
                        (org, repo, lf["path"]),
                    )
                ]
                locks.append(
                    LockFile(
                        path=lf["path"],
                        format=lf["format"],
                        sha=lf["sha"],
                        packages=packages,
                    )
                )
            errors = [
                r["message"]
                for r in conn.execute(
                    "SELECT message FROM repo_error WHERE org = ? AND repo = ?",
                    (org, repo),
                )
            ]
            repos.append(RepoSnapshot(name=repo, lock_files=locks, errors=errors))
        projects_list.append(ProjectSnapshot(org=org, repos=repos))

    aggregated: list[AggregatedRow] = []
    for row in conn.execute(
        "SELECT format, name, version, imported_at, max_threat_level "
        "FROM aggregated_package ORDER BY format, name COLLATE NOCASE, version"
    ):
        orgs = [
            r["org"]
            for r in conn.execute(
                "SELECT org FROM aggregated_package_org "
                "WHERE format = ? AND name = ? AND version = ? "
                "ORDER BY org COLLATE NOCASE",
                (row["format"], row["name"], row["version"]),
            )
        ]
        aggregated.append(
            AggregatedRow(
                format=row["format"],
                name=row["name"],
                version=row["version"],
                imported_at=row["imported_at"],
                max_threat_level=row["max_threat_level"],
                organizations=orgs,
            )
        )
    return Snapshot(collected_at=collected_at, projects=projects_list, aggregated=aggregated)


def _delete_org_snapshot(conn: sqlite3.Connection, org: str) -> None:
    conn.execute(
        "DELETE FROM lock_package WHERE org = ?",
        (org,),
    )
    conn.execute("DELETE FROM lock_file WHERE org = ?", (org,))
    conn.execute("DELETE FROM repo_error WHERE org = ?", (org,))


def _write_projects(conn: sqlite3.Connection, projects) -> None:
    for proj in projects:
        _delete_org_snapshot(conn, proj.org)
        for repo in proj.repos:
            for lf in repo.lock_files:
                conn.execute(
                    "INSERT INTO lock_file (org, repo, path, format, sha) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (proj.org, repo.name, lf.path, lf.format, lf.sha),
                )
                for pkg in lf.packages:
                    conn.execute(
                        "INSERT INTO lock_package "
                        "(org, repo, lock_path, name, version) VALUES (?, ?, ?, ?, ?)",
                        (proj.org, repo.name, lf.path, pkg.name, pkg.version),
                    )
            for msg in repo.errors:
                conn.execute(
                    "INSERT INTO repo_error (org, repo, message) VALUES (?, ?, ?)",
                    (proj.org, repo.name, msg),
                )


def _write_aggregated(conn: sqlite3.Connection, rows) -> None:
    conn.execute("DELETE FROM aggregated_package_org")
    conn.execute("DELETE FROM aggregated_package")
    for row in rows:
        conn.execute(
            "INSERT INTO aggregated_package "
            "(format, name, version, imported_at, max_threat_level) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                row.format,
                row.name,
                row.version,
                row.imported_at,
                row.max_threat_level,
            ),
        )
        for org in row.organizations:
            conn.execute(
                "INSERT INTO aggregated_package_org (format, name, version, org) "
                "VALUES (?, ?, ?, ?)",
                (row.format, row.name, row.version, org),
            )


def save_snapshot_to_conn(conn: sqlite3.Connection, snap) -> None:
    conn.execute(
        "INSERT INTO package_snapshot_meta (id, collected_at) VALUES (1, ?) "
        "ON CONFLICT(id) DO UPDATE SET collected_at = excluded.collected_at",
        (snap.collected_at,),
    )
    orgs_in_snap = {p.org for p in snap.projects}
    for org in orgs_in_snap:
        _delete_org_snapshot(conn, org)
    _write_projects(conn, snap.projects)
    _write_aggregated(conn, snap.aggregated)


def save_snapshot(snap) -> None:
    conn = connect()
    try:
        save_snapshot_to_conn(conn, snap)
        conn.commit()
    finally:
        conn.close()


def load_snapshot():
    conn = connect()
    try:
        return load_snapshot_from_conn(conn)
    finally:
        conn.close()


def load_vulnerability_index_from_conn(
    conn: sqlite3.Connection,
) -> dict[tuple[str, str, str], float]:
    index: dict[tuple[str, str, str], float] = {}
    for row in conn.execute(
        "SELECT format, name, version, max_threat_level FROM vulnerability_entry"
    ):
        index[(row["format"], row["name"], row["version"])] = float(
            row["max_threat_level"]
        )
    return index


def load_vulnerability_index() -> dict[tuple[str, str, str], float]:
    conn = connect()
    try:
        return load_vulnerability_index_from_conn(conn)
    finally:
        conn.close()


def save_vulnerability_index_to_conn(
    conn: sqlite3.Connection,
    index: dict[tuple[str, str, str], float],
    *,
    collected_at: str | None = None,
) -> None:
    stamp = collected_at or datetime.now(tz=UTC).isoformat()
    conn.execute(
        "INSERT INTO vulnerability_meta (id, collected_at) VALUES (1, ?) "
        "ON CONFLICT(id) DO UPDATE SET collected_at = excluded.collected_at",
        (stamp,),
    )
    conn.execute("DELETE FROM vulnerability_entry")
    for (fmt, name, version), score in sorted(index.items()):
        conn.execute(
            "INSERT INTO vulnerability_entry (format, name, version, max_threat_level) "
            "VALUES (?, ?, ?, ?)",
            (fmt, name, version, score),
        )


def save_vulnerability_index(index: dict[tuple[str, str, str], float]) -> None:
    conn = connect()
    try:
        save_vulnerability_index_to_conn(conn, index)
        conn.commit()
    finally:
        conn.close()


def rebuild_vulnerability_index_from_proxy_health(
    conn: sqlite3.Connection,
) -> dict[tuple[str, str, str], float]:
    from app.services.proxy_health_store import load_all_cached_reports

    index: dict[tuple[str, str, str], float] = {}
    for fmt, report in load_all_cached_reports(conn).items():
        for item in report.vulnerabilities:
            if item.threat_level is None or not item.artifact or not item.version:
                continue
            key = (fmt, import_name_key(item.artifact, fmt), item.version)
            prev = index.get(key)
            if prev is None or item.threat_level > prev:
                index[key] = float(item.threat_level)
    save_vulnerability_index_to_conn(conn, index)
    return index
