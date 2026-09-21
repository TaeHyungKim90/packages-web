from datetime import UTC, datetime

import pytest
from app.db import connect, init_schema
from app.schemas import (
    ProxyHealthResponse,
    ProxyHealthVulnerability,
    ProxyHealthVulnOverrideUpdate,
)
from app.services.proxy_health_store import (
    apply_fixed_versions_from_index,
    apply_vuln_overrides,
    delete_vuln_override,
    get_proxy_health_cached,
    get_proxy_health_from_db,
    load_vuln_overrides,
    save_proxy_health_to_conn,
    save_vuln_override,
    vuln_override_map,
)


@pytest.mark.asyncio
async def test_get_proxy_health_reuses_db_fixed_and_osv_only_missing(monkeypatch):
    conn = connect()
    init_schema(conn)
    save_proxy_health_to_conn(
        conn,
        ProxyHealthResponse(
            ecosystem="pypi",
            repository="old",
            generated_at=datetime.now(tz=UTC).isoformat(),
            vulnerabilities=[
                ProxyHealthVulnerability(
                    threat_level=8.0,
                    problem_code="CVE-1",
                    artifact="foo",
                    version="1.0.0",
                    fixed_version="1.2.0",
                )
            ],
            licenses=[],
        ),
    )
    conn.commit()
    conn.close()

    fresh = ProxyHealthResponse(
        ecosystem="pypi",
        repository="pypi-proxy-health",
        generated_at=datetime.now(tz=UTC).isoformat(),
        vulnerabilities=[
            ProxyHealthVulnerability(
                threat_level=8.0,
                problem_code="CVE-1",
                artifact="foo",
                version="1.0.0",
            ),
            ProxyHealthVulnerability(
                threat_level=7.0,
                problem_code="CVE-2",
                artifact="bar",
                version="2.0.0",
            ),
        ],
        licenses=[],
    )

    async def _fetch(_eco: str):
        return fresh

    seen: list[list[ProxyHealthVulnerability]] = []

    async def _enrich(_eco: str, vulns: list[ProxyHealthVulnerability], **kwargs):
        seen.append(vulns)
        return [
            v
            if v.fixed_version
            else v.model_copy(update={"fixed_version": "9.9.9"})
            for v in vulns
        ]

    monkeypatch.setattr(
        "app.services.proxy_health_store.fetch_proxy_health",
        _fetch,
    )
    monkeypatch.setattr(
        "app.services.proxy_health_store.enrich_fixed_versions",
        _enrich,
    )
    result = await get_proxy_health_cached("pypi", force_refresh=True)
    assert result.repository == "pypi-proxy-health"
    by_name = {v.artifact: v.fixed_version for v in result.vulnerabilities}
    assert by_name["foo"] == "1.2.0"
    assert by_name["bar"] == "9.9.9"
    assert seen[0][0].fixed_version == "1.2.0"
    assert seen[0][1].fixed_version is None
    assert result.fetched_at


def test_apply_fixed_versions_from_index():
    vulns = [
        ProxyHealthVulnerability(
            threat_level=1,
            problem_code="CVE-1",
            artifact="foo",
            version="1.0.0",
        )
    ]
    out = apply_fixed_versions_from_index(
        vulns, {("foo", "1.0.0", "CVE-1"): "2.0.0"}
    )
    assert out[0].fixed_version == "2.0.0"


def test_apply_fixed_versions_skips_non_newer_cache():
    vulns = [
        ProxyHealthVulnerability(
            threat_level=5,
            problem_code="CVE-1",
            artifact="pkg",
            version="1.106.0",
        )
    ]
    out = apply_fixed_versions_from_index(
        vulns, {("pkg", "1.106.0", "CVE-1"): "1.106.0"}
    )
    assert out[0].fixed_version is None


def test_apply_fixed_versions_skips_git_sha_cache():
    vulns = [
        ProxyHealthVulnerability(
            threat_level=9,
            problem_code="CVE-2026-78207",
            artifact="exceljs",
            version="4.4.0",
            fixed_version="37149551343c6305aa8aca4f43567c1091102287",
        )
    ]
    out = apply_fixed_versions_from_index(
        vulns,
        {
            ("exceljs", "4.4.0", "CVE-2026-78207"): (
                "37149551343c6305aa8aca4f43567c1091102287"
            )
        },
    )
    assert out[0].fixed_version is None


@pytest.mark.asyncio
async def test_get_proxy_health_falls_back_to_db_on_nexus_error(monkeypatch):
    conn = connect()
    init_schema(conn)
    save_proxy_health_to_conn(
        conn,
        ProxyHealthResponse(
            ecosystem="pypi",
            repository="cached-repo",
            generated_at=datetime.now(tz=UTC).isoformat(),
            vulnerabilities=[],
            licenses=[],
        ),
    )
    conn.commit()
    conn.close()

    async def _fail(_eco: str):
        raise RuntimeError("nexus down")

    monkeypatch.setattr(
        "app.services.proxy_health_store.fetch_proxy_health",
        _fail,
    )
    result = await get_proxy_health_cached("pypi", force_refresh=True)
    assert result.repository == "cached-repo"


def test_apply_vuln_overrides_sets_fixed_version():
    from app.schemas import ProxyHealthVulnOverride

    vulns = [
        ProxyHealthVulnerability(
            threat_level=5,
            problem_code="CVE-1",
            artifact="pkg",
            version="1.0.0",
            fixed_version="9.9.9",
        )
    ]
    overrides = vuln_override_map(
        [
            ProxyHealthVulnOverride(
                problem_code="CVE-1",
                artifact="pkg",
                fixed_version="2.0.0",
                remark="manual",
                updated_at="2026-01-01T00:00:00+00:00",
            )
        ]
    )
    out = apply_vuln_overrides(vulns, overrides)
    assert out[0].fixed_version == "2.0.0"


def test_finalize_keeps_resolved_items_with_flag():
    from app.schemas import ProxyHealthVulnOverride
    from app.services.proxy_health_store import _finalize_report

    report = ProxyHealthResponse(
        ecosystem="npm",
        repository="npm-proxy-health",
        vulnerabilities=[
            ProxyHealthVulnerability(
                threat_level=5,
                problem_code="CVE-OPEN",
                artifact="left",
                version="1.0.0",
                fixed_version="2.0.0",
            ),
            ProxyHealthVulnerability(
                threat_level=5,
                problem_code="CVE-FIXED",
                artifact="done",
                version="2.0.0",
                fixed_version="2.0.0",
            ),
            ProxyHealthVulnerability(
                threat_level=5,
                problem_code="CVE-FP",
                artifact="noise",
                version="1.0.0",
            ),
        ],
    )
    overrides = [
        ProxyHealthVulnOverride(
            problem_code="CVE-FP",
            artifact="noise",
            fixed_version="정상버전(오탐)",
            remark="오탐",
            updated_at="2026-01-01T00:00:00+00:00",
        )
    ]
    out = _finalize_report(report, overrides)
    by_code = {v.problem_code: v for v in out.vulnerabilities}
    assert set(by_code) == {"CVE-OPEN", "CVE-FIXED", "CVE-FP"}
    assert by_code["CVE-OPEN"].resolved is False
    assert by_code["CVE-FIXED"].resolved is True
    assert by_code["CVE-FP"].resolved is True


@pytest.mark.asyncio
async def test_get_proxy_health_applies_override_and_skips_osv(monkeypatch):
    conn = connect()
    init_schema(conn)
    save_vuln_override(
        conn,
        "pypi",
        ProxyHealthVulnOverrideUpdate(
            problem_code="CVE-1",
            artifact="pkg",
            fixed_version="3.0.0",
            remark="note",
        ),
    )
    conn.commit()
    conn.close()

    fresh = ProxyHealthResponse(
        ecosystem="pypi",
        repository="pypi-proxy-health",
        generated_at=datetime.now(tz=UTC).isoformat(),
        vulnerabilities=[
            ProxyHealthVulnerability(
                threat_level=5,
                problem_code="CVE-1",
                artifact="pkg",
                version="1.0.0",
            )
        ],
        licenses=[],
    )

    async def _fetch(_eco: str):
        return fresh

    async def _enrich(_eco: str, vulns, **kwargs):
        assert kwargs.get("skip_override_keys") == {("CVE-1", "pkg")}
        return [v.model_copy(update={"fixed_version": "9.9.9"}) for v in vulns]

    monkeypatch.setattr(
        "app.services.proxy_health_store.fetch_proxy_health", _fetch
    )
    monkeypatch.setattr(
        "app.services.proxy_health_store.enrich_fixed_versions", _enrich
    )
    result = await get_proxy_health_cached("pypi")
    assert result.vulnerabilities[0].fixed_version == "3.0.0"
    assert result.vulnerability_overrides[0].remark == "note"


def test_save_and_delete_vuln_override():
    conn = connect()
    init_schema(conn)
    saved = save_vuln_override(
        conn,
        "pypi",
        ProxyHealthVulnOverrideUpdate(
            problem_code="CVE-1",
            artifact="foo",
            fixed_version="",
            remark="미해결",
        ),
    )
    conn.commit()
    assert saved.fixed_version is None
    loaded = load_vuln_overrides(conn, "pypi")
    assert len(loaded) == 1
    assert loaded[0].remark == "미해결"
    assert delete_vuln_override(conn, "pypi", "CVE-1", "foo")
    conn.commit()
    assert load_vuln_overrides(conn, "pypi") == []
    conn.close()


def test_get_proxy_health_from_db_applies_overrides():
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
                    threat_level=9,
                    problem_code="CVE-1",
                    problem_url="",
                    group="",
                    artifact="pkg-a",
                    version="1.0.0",
                    imported_at=None,
                    fixed_version="1.1.0",
                )
            ],
            licenses=[],
        ),
    )
    save_vuln_override(
        conn,
        "pypi",
        ProxyHealthVulnOverrideUpdate(
            problem_code="CVE-1",
            artifact="pkg-a",
            fixed_version="2.0.0",
            remark="manual",
        ),
    )
    conn.commit()
    conn.close()

    report = get_proxy_health_from_db("pypi")
    assert report.repository == "pypi-proxy-health"
    assert report.vulnerabilities[0].fixed_version == "2.0.0"
    assert report.vulnerability_overrides[0].remark == "manual"


def test_get_proxy_health_from_db_missing_raises():
    with pytest.raises(LookupError):
        get_proxy_health_from_db("pypi")


@pytest.mark.asyncio
async def test_get_proxy_health_uses_ttl_cache(monkeypatch):
    monkeypatch.setattr(
        "app.services.proxy_health_store.settings.proxy_health_ttl_seconds",
        7200,
    )
    conn = connect()
    init_schema(conn)
    save_proxy_health_to_conn(
        conn,
        ProxyHealthResponse(
            ecosystem="pypi",
            repository="cached-fresh",
            generated_at="2026-01-01T00:00:00+00:00",
            vulnerabilities=[],
            licenses=[],
        ),
    )
    conn.commit()
    conn.close()

    async def _fetch(_eco: str):
        raise AssertionError("should not fetch while TTL is fresh")

    monkeypatch.setattr(
        "app.services.proxy_health_store.fetch_proxy_health",
        _fetch,
    )
    result = await get_proxy_health_cached("pypi")
    assert result.repository == "cached-fresh"
    assert result.fetched_at


@pytest.mark.asyncio
async def test_get_proxy_health_force_refresh_bypasses_ttl(monkeypatch):
    monkeypatch.setattr(
        "app.services.proxy_health_store.settings.proxy_health_ttl_seconds",
        7200,
    )
    conn = connect()
    init_schema(conn)
    save_proxy_health_to_conn(
        conn,
        ProxyHealthResponse(
            ecosystem="pypi",
            repository="old-cache",
            generated_at="2026-01-01T00:00:00+00:00",
            vulnerabilities=[],
            licenses=[],
        ),
    )
    conn.commit()
    conn.close()

    async def _fetch(_eco: str):
        return ProxyHealthResponse(
            ecosystem="pypi",
            repository="live-repo",
            generated_at="2026-09-08T00:00:00+00:00",
            vulnerabilities=[],
            licenses=[],
        )

    async def _enrich(_eco: str, vulns, **kwargs):
        return vulns

    monkeypatch.setattr(
        "app.services.proxy_health_store.fetch_proxy_health",
        _fetch,
    )
    monkeypatch.setattr(
        "app.services.proxy_health_store.enrich_fixed_versions",
        _enrich,
    )
    result = await get_proxy_health_cached("pypi", force_refresh=True)
    assert result.repository == "live-repo"
    assert result.fetched_at


@pytest.mark.asyncio
async def test_get_proxy_health_expired_ttl_refetches(monkeypatch):
    from datetime import timedelta

    monkeypatch.setattr(
        "app.services.proxy_health_store.settings.proxy_health_ttl_seconds",
        60,
    )
    conn = connect()
    init_schema(conn)
    save_proxy_health_to_conn(
        conn,
        ProxyHealthResponse(
            ecosystem="pypi",
            repository="stale-cache",
            generated_at="2026-01-01T00:00:00+00:00",
            vulnerabilities=[],
            licenses=[],
        ),
    )
    stale = (datetime.now(tz=UTC) - timedelta(hours=3)).isoformat()
    conn.execute(
        "UPDATE proxy_health_meta SET fetched_at = ? WHERE ecosystem = ?",
        (stale, "pypi"),
    )
    conn.commit()
    conn.close()

    async def _fetch(_eco: str):
        return ProxyHealthResponse(
            ecosystem="pypi",
            repository="refetched",
            generated_at="2026-09-08T00:00:00+00:00",
            vulnerabilities=[],
            licenses=[],
        )

    async def _enrich(_eco: str, vulns, **kwargs):
        return vulns

    monkeypatch.setattr(
        "app.services.proxy_health_store.fetch_proxy_health",
        _fetch,
    )
    monkeypatch.setattr(
        "app.services.proxy_health_store.enrich_fixed_versions",
        _enrich,
    )
    result = await get_proxy_health_cached("pypi")
    assert result.repository == "refetched"


@pytest.mark.asyncio
async def test_get_proxy_health_fresh_report_skips_live_even_if_ttl_expired(
    monkeypatch,
):
    """보고서(generated_at)가 24h 이내면 fetched_at TTL이 지나도 Nexus를 치지 않는다."""
    from datetime import timedelta

    monkeypatch.setattr(
        "app.services.proxy_health_store.settings.proxy_health_ttl_seconds",
        60,
    )
    monkeypatch.setattr(
        "app.services.proxy_health_store.settings.proxy_health_report_ttl_seconds",
        86400,
    )
    conn = connect()
    init_schema(conn)
    fresh_report = (datetime.now(tz=UTC) - timedelta(hours=3)).isoformat()
    save_proxy_health_to_conn(
        conn,
        ProxyHealthResponse(
            ecosystem="pypi",
            repository="report-fresh",
            generated_at=fresh_report,
            vulnerabilities=[],
            licenses=[],
        ),
    )
    stale_fetch = (datetime.now(tz=UTC) - timedelta(hours=5)).isoformat()
    conn.execute(
        "UPDATE proxy_health_meta SET fetched_at = ? WHERE ecosystem = ?",
        (stale_fetch, "pypi"),
    )
    conn.commit()
    conn.close()

    async def _fetch(_eco: str):
        raise AssertionError("should not fetch while Nexus report is fresh")

    monkeypatch.setattr(
        "app.services.proxy_health_store.fetch_proxy_health",
        _fetch,
    )
    result = await get_proxy_health_cached("pypi")
    assert result.repository == "report-fresh"
