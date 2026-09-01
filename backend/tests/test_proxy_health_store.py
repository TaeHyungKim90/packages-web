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
    result = await get_proxy_health_cached("pypi")
    assert result.repository == "pypi-proxy-health"
    by_name = {v.artifact: v.fixed_version for v in result.vulnerabilities}
    assert by_name["foo"] == "1.2.0"
    assert by_name["bar"] == "9.9.9"
    assert seen[0][0].fixed_version == "1.2.0"
    assert seen[0][1].fixed_version is None


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
    result = await get_proxy_health_cached("pypi")
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
