from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import yaml

from app.config import settings

SCHEMA_VERSION = "1"

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ghes_org (
    name TEXT PRIMARY KEY,
    managed INTEGER NOT NULL DEFAULT 0,
    present INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS ghes_repo (
    org_name TEXT NOT NULL REFERENCES ghes_org(name) ON DELETE CASCADE,
    name TEXT NOT NULL,
    managed INTEGER NOT NULL DEFAULT 0,
    present INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (org_name, name)
);

CREATE TABLE IF NOT EXISTS ghes_inventory_meta (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    synced_at TEXT
);

CREATE TABLE IF NOT EXISTS package_snapshot_meta (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    collected_at TEXT
);

CREATE TABLE IF NOT EXISTS lock_file (
    org TEXT NOT NULL,
    repo TEXT NOT NULL,
    path TEXT NOT NULL,
    format TEXT NOT NULL,
    sha TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (org, repo, path)
);

CREATE TABLE IF NOT EXISTS lock_package (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    org TEXT NOT NULL,
    repo TEXT NOT NULL,
    lock_path TEXT NOT NULL,
    name TEXT NOT NULL,
    version TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_lock_package_lookup
    ON lock_package (org, repo, lock_path);

CREATE TABLE IF NOT EXISTS repo_error (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    org TEXT NOT NULL,
    repo TEXT NOT NULL,
    message TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS aggregated_package (
    format TEXT NOT NULL,
    name TEXT NOT NULL,
    version TEXT NOT NULL,
    imported_at TEXT,
    max_threat_level REAL,
    PRIMARY KEY (format, name, version)
);

CREATE TABLE IF NOT EXISTS aggregated_package_org (
    format TEXT NOT NULL,
    name TEXT NOT NULL,
    version TEXT NOT NULL,
    org TEXT NOT NULL,
    PRIMARY KEY (format, name, version, org),
    FOREIGN KEY (format, name, version)
        REFERENCES aggregated_package(format, name, version) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS vulnerability_meta (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    collected_at TEXT
);

CREATE TABLE IF NOT EXISTS vulnerability_entry (
    format TEXT NOT NULL,
    name TEXT NOT NULL,
    version TEXT NOT NULL,
    max_threat_level REAL NOT NULL,
    PRIMARY KEY (format, name, version)
);

CREATE TABLE IF NOT EXISTS proxy_health_meta (
    ecosystem TEXT PRIMARY KEY,
    repository TEXT NOT NULL,
    generated_at TEXT,
    fetched_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS proxy_health_vulnerability (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ecosystem TEXT NOT NULL REFERENCES proxy_health_meta(ecosystem) ON DELETE CASCADE,
    threat_level REAL,
    problem_code TEXT NOT NULL DEFAULT '',
    problem_url TEXT NOT NULL DEFAULT '',
    group_name TEXT NOT NULL DEFAULT '',
    artifact TEXT NOT NULL,
    version TEXT NOT NULL,
    imported_at TEXT
);

CREATE TABLE IF NOT EXISTS proxy_health_license (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ecosystem TEXT NOT NULL REFERENCES proxy_health_meta(ecosystem) ON DELETE CASCADE,
    license_threat TEXT NOT NULL DEFAULT '',
    declared_license TEXT NOT NULL DEFAULT '',
    observed_licenses TEXT NOT NULL DEFAULT '',
    group_name TEXT NOT NULL DEFAULT '',
    artifact TEXT NOT NULL,
    version TEXT NOT NULL,
    security_issues INTEGER,
    imported_at TEXT
);
"""


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def resolve_db_path() -> Path:
    configured = (settings.packages_web_db_path or "").strip()
    if configured:
        return Path(configured)
    return repo_root() / "config" / "packages-web.sqlite3"


def connect() -> sqlite3.Connection:
    path = resolve_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def get_meta(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


def init_schema(conn: sqlite3.Connection | None = None) -> None:
    own = conn is None
    if own:
        conn = connect()
    assert conn is not None
    conn.executescript(SCHEMA_SQL)
    _ensure_column(conn, "ghes_org", "present", "present INTEGER NOT NULL DEFAULT 1")
    _ensure_column(conn, "ghes_repo", "present", "present INTEGER NOT NULL DEFAULT 1")
    set_meta(conn, "schema_version", SCHEMA_VERSION)
    conn.commit()
    if own:
        conn.close()


def _legacy_yaml_path(name: str) -> Path:
    return repo_root() / "config" / name


def _migrate_orgs_yaml(conn: sqlite3.Connection, path: Path) -> bool:
    if not path.is_file():
        return False
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        return False
    from app.services.ghes_inventory import _parse_org
    from app.services.store_orgs import save_orgs_to_conn

    orgs = []
    for item in raw.get("organizations") or []:
        org = _parse_org(item)
        if org is not None:
            orgs.append(org)
    if not orgs:
        return False
    save_orgs_to_conn(conn, orgs)
    return True


def _migrate_packages_yaml(conn: sqlite3.Connection, path: Path) -> bool:
    if not path.is_file():
        return False
    from app.services.store_packages import import_snapshot_yaml

    import_snapshot_yaml(conn, path)
    return True


def _migrate_vulnerabilities_yaml(conn: sqlite3.Connection, path: Path) -> bool:
    if not path.is_file():
        return False
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        return False
    from app.services.nexus import import_name_key
    from app.services.store_packages import save_vulnerability_index_to_conn

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
    if not index:
        return False
    collected = str(raw.get("collected_at") or "") or datetime.now(tz=UTC).isoformat()
    save_vulnerability_index_to_conn(conn, index, collected_at=collected)
    return True


def migrate_yaml_if_needed() -> None:
    conn = connect()
    try:
        init_schema(conn)
        if get_meta(conn, "yaml_migrated") == "1":
            return
        migrated_any = False
        if _migrate_orgs_yaml(conn, _legacy_yaml_path("ghes-orgs.yaml")):
            migrated_any = True
        if _migrate_packages_yaml(conn, _legacy_yaml_path("ghes-project-packages.yaml")):
            migrated_any = True
        if _migrate_vulnerabilities_yaml(
            conn, _legacy_yaml_path("ghes-package-vulnerabilities.yaml")
        ):
            migrated_any = True
        if migrated_any or conn.execute("SELECT COUNT(*) FROM ghes_org").fetchone()[0]:
            set_meta(conn, "yaml_migrated", "1")
        conn.commit()
    finally:
        conn.close()
