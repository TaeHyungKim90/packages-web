from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

from app.db import connect
from app.schemas import ProxyHealthLicense, ProxyHealthResponse, ProxyHealthVulnerability
from app.services.nexus_health import fetch_proxy_health

PROXY_HEALTH_TTL = timedelta(hours=24)


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _cache_age(generated_at: str | None, fetched_at: str) -> timedelta | None:
    anchor = _parse_iso(generated_at) or _parse_iso(fetched_at)
    if anchor is None:
        return None
    if anchor.tzinfo is None:
        anchor = anchor.replace(tzinfo=UTC)
    return datetime.now(tz=UTC) - anchor


def is_cache_fresh(generated_at: str | None, fetched_at: str) -> bool:
    age = _cache_age(generated_at, fetched_at)
    if age is None:
        return False
    return age < PROXY_HEALTH_TTL


def _load_report(conn: sqlite3.Connection, ecosystem: str) -> ProxyHealthResponse | None:
    meta = conn.execute(
        "SELECT repository, generated_at, fetched_at FROM proxy_health_meta "
        "WHERE ecosystem = ?",
        (ecosystem,),
    ).fetchone()
    if meta is None:
        return None
    vulnerabilities = [
        ProxyHealthVulnerability(
            threat_level=row["threat_level"],
            problem_code=row["problem_code"],
            problem_url=row["problem_url"],
            group=row["group_name"],
            artifact=row["artifact"],
            version=row["version"],
            imported_at=row["imported_at"],
        )
        for row in conn.execute(
            "SELECT threat_level, problem_code, problem_url, group_name, "
            "artifact, version, imported_at "
            "FROM proxy_health_vulnerability WHERE ecosystem = ?",
            (ecosystem,),
        )
    ]
    licenses = [
        ProxyHealthLicense(
            license_threat=row["license_threat"],
            declared_license=row["declared_license"],
            observed_licenses=row["observed_licenses"],
            group=row["group_name"],
            artifact=row["artifact"],
            version=row["version"],
            security_issues=row["security_issues"],
            imported_at=row["imported_at"],
        )
        for row in conn.execute(
            "SELECT license_threat, declared_license, observed_licenses, "
            "group_name, artifact, version, security_issues, imported_at "
            "FROM proxy_health_license WHERE ecosystem = ?",
            (ecosystem,),
        )
    ]
    return ProxyHealthResponse(
        ecosystem=ecosystem,
        repository=meta["repository"],
        generated_at=meta["generated_at"],
        vulnerabilities=vulnerabilities,
        licenses=licenses,
    )


def save_proxy_health_to_conn(
    conn: sqlite3.Connection, report: ProxyHealthResponse
) -> None:
    eco = report.ecosystem
    fetched_at = datetime.now(tz=UTC).isoformat()
    conn.execute("DELETE FROM proxy_health_meta WHERE ecosystem = ?", (eco,))
    conn.execute(
        "INSERT INTO proxy_health_meta "
        "(ecosystem, repository, generated_at, fetched_at) "
        "VALUES (?, ?, ?, ?)",
        (eco, report.repository, report.generated_at, fetched_at),
    )
    for item in report.vulnerabilities:
        conn.execute(
            "INSERT INTO proxy_health_vulnerability "
            "(ecosystem, threat_level, problem_code, problem_url, group_name, "
            "artifact, version, imported_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                eco,
                item.threat_level,
                item.problem_code,
                item.problem_url,
                item.group,
                item.artifact,
                item.version,
                item.imported_at,
            ),
        )
    for item in report.licenses:
        conn.execute(
            "INSERT INTO proxy_health_license "
            "(ecosystem, license_threat, declared_license, observed_licenses, "
            "group_name, artifact, version, security_issues, imported_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                eco,
                item.license_threat,
                item.declared_license,
                item.observed_licenses,
                item.group,
                item.artifact,
                item.version,
                item.security_issues,
                item.imported_at,
            ),
        )


def load_all_cached_reports(
    conn: sqlite3.Connection,
) -> dict[str, ProxyHealthResponse]:
    out: dict[str, ProxyHealthResponse] = {}
    for row in conn.execute("SELECT ecosystem FROM proxy_health_meta"):
        report = _load_report(conn, row["ecosystem"])
        if report is not None:
            out[row["ecosystem"]] = report
    return out


async def get_proxy_health_cached(ecosystem: str) -> ProxyHealthResponse:
    key = ecosystem.lower().strip()
    conn = connect()
    try:
        meta = conn.execute(
            "SELECT generated_at, fetched_at FROM proxy_health_meta WHERE ecosystem = ?",
            (key,),
        ).fetchone()
        cached = _load_report(conn, key) if meta else None
        if cached and meta and is_cache_fresh(meta["generated_at"], meta["fetched_at"]):
            return cached
    finally:
        conn.close()

    try:
        fresh = await fetch_proxy_health(key)
    except Exception:
        if cached is not None:
            return cached
        raise

    conn = connect()
    try:
        save_proxy_health_to_conn(conn, fresh)
        conn.commit()
    finally:
        conn.close()
    return fresh


async def ensure_all_proxy_health_cached() -> None:
    for fmt in ("pypi", "npm", "nuget"):
        await get_proxy_health_cached(fmt)
