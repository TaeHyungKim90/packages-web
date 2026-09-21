from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

from app.config import settings
from app.db import connect
from app.schemas import (
    ProxyHealthLicense,
    ProxyHealthResponse,
    ProxyHealthVulnerability,
    ProxyHealthVulnOverride,
    ProxyHealthVulnOverrideUpdate,
)
from app.services.nexus_health import fetch_proxy_health
from app.services.osv import (
    _is_newer,
    enrich_fixed_versions,
    is_package_fixed_version,
    is_resolved_or_false_positive,
)


def _row_bool(value: object) -> bool:
    return bool(value) if value is not None else False


def _parse_fetched_at(value: str | None) -> datetime | None:
    text = (value or "").strip()
    if not text:
        return None
    try:
        ts = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    return ts


def cache_is_fresh(fetched_at: str | None, ttl_seconds: int | None = None) -> bool:
    ttl = settings.proxy_health_ttl_seconds if ttl_seconds is None else ttl_seconds
    if ttl <= 0:
        return False
    ts = _parse_fetched_at(fetched_at)
    if ts is None:
        return False
    age = (datetime.now(tz=UTC) - ts).total_seconds()
    return age < ttl


def report_is_fresh(generated_at: str | None, ttl_seconds: int | None = None) -> bool:
    """Nexus 보고서 분석시각(generated_at)이 아직 유효한지."""
    ttl = (
        settings.proxy_health_report_ttl_seconds
        if ttl_seconds is None
        else ttl_seconds
    )
    return cache_is_fresh(generated_at, ttl)


def _should_use_cache(
    cached: ProxyHealthResponse, *, force_refresh: bool
) -> bool:
    if force_refresh:
        return False
    # 보고서가 24h 이내면 Nexus 재조회 불필요
    if report_is_fresh(cached.generated_at):
        return True
    # 보고서는 오래됐어도 최근 live(fetched_at TTL)면 스냅샷 유지
    return cache_is_fresh(cached.fetched_at)


def _load_report(conn: sqlite3.Connection, ecosystem: str) -> ProxyHealthResponse | None:
    meta = conn.execute(
        "SELECT repository, generated_at, fetched_at FROM proxy_health_meta "
        "WHERE ecosystem = ?",
        (ecosystem,),
    ).fetchone()
    if meta is None:
        return None
    vulnerabilities: list[ProxyHealthVulnerability] = []
    for row in conn.execute(
        "SELECT threat_level, problem_code, problem_url, group_name, "
        "artifact, version, imported_at, published_at, fixed_version, in_hosted "
        "FROM proxy_health_vulnerability WHERE ecosystem = ?",
        (ecosystem,),
    ):
        raw_fixed = row["fixed_version"] if "fixed_version" in row.keys() else None
        raw_published = (
            row["published_at"] if "published_at" in row.keys() else None
        )
        vulnerabilities.append(
            ProxyHealthVulnerability(
                threat_level=row["threat_level"],
                problem_code=row["problem_code"],
                problem_url=row["problem_url"],
                group=row["group_name"],
                artifact=row["artifact"],
                version=row["version"],
                imported_at=row["imported_at"],
                published_at=raw_published,
                fixed_version=raw_fixed if is_package_fixed_version(raw_fixed) else None,
                in_hosted=_row_bool(row["in_hosted"] if "in_hosted" in row.keys() else 0),
            )
        )
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
            in_hosted=_row_bool(row["in_hosted"] if "in_hosted" in row.keys() else 0),
        )
        for row in conn.execute(
            "SELECT license_threat, declared_license, observed_licenses, "
            "group_name, artifact, version, security_issues, imported_at, in_hosted "
            "FROM proxy_health_license WHERE ecosystem = ?",
            (ecosystem,),
        )
    ]
    return ProxyHealthResponse(
        ecosystem=ecosystem,
        repository=meta["repository"],
        generated_at=meta["generated_at"],
        fetched_at=meta["fetched_at"],
        vulnerabilities=vulnerabilities,
        licenses=licenses,
    )


def save_proxy_health_to_conn(
    conn: sqlite3.Connection, report: ProxyHealthResponse
) -> str:
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
            "artifact, version, imported_at, published_at, fixed_version, in_hosted) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                eco,
                item.threat_level,
                item.problem_code,
                item.problem_url,
                item.group,
                item.artifact,
                item.version,
                item.imported_at,
                item.published_at,
                item.fixed_version,
                1 if item.in_hosted else 0,
            ),
        )
    for item in report.licenses:
        conn.execute(
            "INSERT INTO proxy_health_license "
            "(ecosystem, license_threat, declared_license, observed_licenses, "
            "group_name, artifact, version, security_issues, imported_at, in_hosted) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
                1 if item.in_hosted else 0,
            ),
        )
    return fetched_at


def load_all_cached_reports(
    conn: sqlite3.Connection,
) -> dict[str, ProxyHealthResponse]:
    out: dict[str, ProxyHealthResponse] = {}
    for row in conn.execute("SELECT ecosystem FROM proxy_health_meta"):
        report = _load_report(conn, row["ecosystem"])
        if report is not None:
            out[row["ecosystem"]] = report
    return out


def load_fixed_version_index(
    conn: sqlite3.Connection, ecosystem: str
) -> dict[tuple[str, str, str], str]:
    """Map (artifact, version, problem_code) -> fixed_version from DB."""
    index: dict[tuple[str, str, str], str] = {}
    try:
        rows = conn.execute(
            "SELECT artifact, version, problem_code, fixed_version "
            "FROM proxy_health_vulnerability "
            "WHERE ecosystem = ? AND fixed_version IS NOT NULL AND fixed_version != ''",
            (ecosystem,),
        )
    except sqlite3.OperationalError:
        return index
    for row in rows:
        fixed = str(row["fixed_version"] or "").strip()
        if not is_package_fixed_version(fixed):
            continue
        version = str(row["version"] or "").strip()
        if version and not _is_newer(fixed, version):
            continue
        key = (
            str(row["artifact"] or ""),
            str(row["version"] or ""),
            str(row["problem_code"] or ""),
        )
        index[key] = fixed
    return index


def load_vuln_overrides(
    conn: sqlite3.Connection, ecosystem: str
) -> list[ProxyHealthVulnOverride]:
    try:
        rows = conn.execute(
            "SELECT problem_code, artifact, fixed_version, remark, updated_at "
            "FROM proxy_health_vuln_override WHERE ecosystem = ? "
            "ORDER BY problem_code, artifact",
            (ecosystem,),
        )
    except sqlite3.OperationalError:
        return []
    out: list[ProxyHealthVulnOverride] = []
    for row in rows:
        raw_fixed = row["fixed_version"]
        fixed = (
            str(raw_fixed).strip()
            if raw_fixed and is_package_fixed_version(str(raw_fixed))
            else None
        )
        out.append(
            ProxyHealthVulnOverride(
                problem_code=str(row["problem_code"] or ""),
                artifact=str(row["artifact"] or ""),
                fixed_version=fixed,
                remark=str(row["remark"] or ""),
                updated_at=str(row["updated_at"] or ""),
            )
        )
    return out


def vuln_override_map(
    overrides: list[ProxyHealthVulnOverride],
) -> dict[tuple[str, str], ProxyHealthVulnOverride]:
    return {(o.problem_code, o.artifact): o for o in overrides}


def save_vuln_override(
    conn: sqlite3.Connection,
    ecosystem: str,
    update: ProxyHealthVulnOverrideUpdate,
) -> ProxyHealthVulnOverride:
    fixed: str | None = None
    if update.fixed_version is not None:
        text = update.fixed_version.strip()
        if text:
            if not is_package_fixed_version(text):
                raise ValueError(f"Invalid fixed version: {text}")
            fixed = text
    updated_at = datetime.now(tz=UTC).isoformat()
    conn.execute(
        "INSERT INTO proxy_health_vuln_override "
        "(ecosystem, problem_code, artifact, fixed_version, remark, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(ecosystem, problem_code, artifact) DO UPDATE SET "
        "fixed_version = excluded.fixed_version, "
        "remark = excluded.remark, "
        "updated_at = excluded.updated_at",
        (
            ecosystem,
            update.problem_code.strip(),
            update.artifact.strip(),
            fixed,
            (update.remark or "").strip(),
            updated_at,
        ),
    )
    return ProxyHealthVulnOverride(
        problem_code=update.problem_code.strip(),
        artifact=update.artifact.strip(),
        fixed_version=fixed,
        remark=(update.remark or "").strip(),
        updated_at=updated_at,
    )


def delete_vuln_override(
    conn: sqlite3.Connection,
    ecosystem: str,
    problem_code: str,
    artifact: str,
) -> bool:
    cur = conn.execute(
        "DELETE FROM proxy_health_vuln_override "
        "WHERE ecosystem = ? AND problem_code = ? AND artifact = ?",
        (ecosystem, problem_code.strip(), artifact.strip()),
    )
    return cur.rowcount > 0


def apply_fixed_versions_from_index(
    vulns: list[ProxyHealthVulnerability],
    index: dict[tuple[str, str, str], str],
) -> list[ProxyHealthVulnerability]:
    if not index:
        return vulns
    out: list[ProxyHealthVulnerability] = []
    for item in vulns:
        if item.fixed_version and is_package_fixed_version(item.fixed_version):
            out.append(item)
            continue
        key = (item.artifact, item.version, item.problem_code)
        cached = index.get(key)
        if cached and is_package_fixed_version(cached) and _is_newer(cached, item.version):
            out.append(item.model_copy(update={"fixed_version": cached}))
        else:
            out.append(
                item
                if not item.fixed_version
                else item.model_copy(update={"fixed_version": None})
            )
    return out


def apply_vuln_overrides(
    vulns: list[ProxyHealthVulnerability],
    overrides: dict[tuple[str, str], ProxyHealthVulnOverride],
) -> list[ProxyHealthVulnerability]:
    if not overrides:
        return vulns
    out: list[ProxyHealthVulnerability] = []
    for item in vulns:
        key = (item.problem_code, item.artifact)
        override = overrides.get(key)
        if override is None:
            out.append(item)
            continue
        out.append(item.model_copy(update={"fixed_version": override.fixed_version}))
    return out


def _finalize_report(
    report: ProxyHealthResponse,
    overrides: list[ProxyHealthVulnOverride],
) -> ProxyHealthResponse:
    override_map = vuln_override_map(overrides)
    applied = apply_vuln_overrides(report.vulnerabilities, override_map)
    vulns: list[ProxyHealthVulnerability] = []
    for item in applied:
        remark = (
            override_map[(item.problem_code, item.artifact)].remark
            if (item.problem_code, item.artifact) in override_map
            else None
        )
        resolved = is_resolved_or_false_positive(
            item.version,
            item.fixed_version,
            remark=remark,
        )
        vulns.append(item.model_copy(update={"resolved": resolved}))
    return report.model_copy(
        update={
            "vulnerabilities": vulns,
            "vulnerability_overrides": overrides,
        }
    )


def get_proxy_health_from_db(ecosystem: str) -> ProxyHealthResponse:
    """저장된 DB 스냅샷과 override만 반영해 반환 (Nexus/OSV 조회 없음)."""
    key = ecosystem.lower().strip()
    conn = connect()
    try:
        report = _load_report(conn, key)
        if report is None:
            raise LookupError(f"No cached proxy health data for ecosystem: {key}")
        overrides = load_vuln_overrides(conn, key)
        return _finalize_report(report, overrides)
    finally:
        conn.close()


async def get_proxy_health_cached(
    ecosystem: str, *, force_refresh: bool = False
) -> ProxyHealthResponse:
    """보고서 24h·fetched_at TTL 안이면 DB, 만료/force 시 Nexus + OSV 후 저장."""
    key = ecosystem.lower().strip()
    cached: ProxyHealthResponse | None = None
    fixed_index: dict[tuple[str, str, str], str] = {}
    overrides: list[ProxyHealthVulnOverride] = []
    conn = connect()
    try:
        cached = _load_report(conn, key)
        fixed_index = load_fixed_version_index(conn, key)
        overrides = load_vuln_overrides(conn, key)
    finally:
        conn.close()

    if cached is not None and _should_use_cache(cached, force_refresh=force_refresh):
        return _finalize_report(cached, overrides)

    override_map = vuln_override_map(overrides)
    skip_keys = set(override_map.keys())

    try:
        fresh = await fetch_proxy_health(key)
    except Exception:
        if cached is not None:
            return _finalize_report(cached, overrides)
        raise

    seeded = apply_fixed_versions_from_index(fresh.vulnerabilities, fixed_index)
    enriched = await enrich_fixed_versions(key, seeded, skip_override_keys=skip_keys)
    vulns = apply_vuln_overrides(enriched, override_map)
    fresh = fresh.model_copy(
        update={
            "vulnerabilities": vulns,
            "vulnerability_overrides": overrides,
        }
    )

    conn = connect()
    try:
        fetched_at = save_proxy_health_to_conn(conn, fresh)
        conn.commit()
    finally:
        conn.close()
    return _finalize_report(
        fresh.model_copy(update={"fetched_at": fetched_at}),
        overrides,
    )


async def ensure_all_proxy_health_cached() -> None:
    for fmt in ("pypi", "npm", "nuget"):
        await get_proxy_health_cached(fmt)
