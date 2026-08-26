from datetime import UTC, datetime, timedelta

import pytest
from app.db import connect, init_schema
from app.schemas import ProxyHealthResponse
from app.services.proxy_health_store import (
    get_proxy_health_cached,
    is_cache_fresh,
    save_proxy_health_to_conn,
)


def test_is_cache_fresh_within_24h():
    now = datetime.now(tz=UTC)
    fetched = (now - timedelta(hours=12)).isoformat()
    assert is_cache_fresh(None, fetched) is True


def test_is_cache_fresh_after_24h():
    now = datetime.now(tz=UTC)
    fetched = (now - timedelta(hours=25)).isoformat()
    assert is_cache_fresh(None, fetched) is False


@pytest.mark.asyncio
async def test_get_proxy_health_cached_uses_db_when_fresh(monkeypatch):
    report = ProxyHealthResponse(
        ecosystem="pypi",
        repository="pypi-proxy-health",
        generated_at=datetime.now(tz=UTC).isoformat(),
        vulnerabilities=[],
        licenses=[],
    )
    conn = connect()
    init_schema(conn)
    save_proxy_health_to_conn(conn, report)
    conn.commit()
    conn.close()

    async def _fail(_eco: str):
        raise AssertionError("Nexus must not be called when cache is fresh")

    monkeypatch.setattr(
        "app.services.proxy_health_store.fetch_proxy_health",
        _fail,
    )
    result = await get_proxy_health_cached("pypi")
    assert result.repository == "pypi-proxy-health"


@pytest.mark.asyncio
async def test_get_proxy_health_cached_refreshes_when_stale(monkeypatch):
    conn = connect()
    init_schema(conn)
    stale = ProxyHealthResponse(
        ecosystem="pypi",
        repository="old",
        generated_at=(datetime.now(tz=UTC) - timedelta(hours=30)).isoformat(),
        vulnerabilities=[],
        licenses=[],
    )
    save_proxy_health_to_conn(conn, stale)
    conn.execute(
        "UPDATE proxy_health_meta SET fetched_at = ? WHERE ecosystem = ?",
        ((datetime.now(tz=UTC) - timedelta(hours=30)).isoformat(), "pypi"),
    )
    conn.commit()
    conn.close()

    fresh = ProxyHealthResponse(
        ecosystem="pypi",
        repository="pypi-proxy-health",
        generated_at=datetime.now(tz=UTC).isoformat(),
        vulnerabilities=[],
        licenses=[],
    )
    calls = {"n": 0}

    async def _fetch(_eco: str):
        calls["n"] += 1
        return fresh

    monkeypatch.setattr(
        "app.services.proxy_health_store.fetch_proxy_health",
        _fetch,
    )
    result = await get_proxy_health_cached("pypi")
    assert calls["n"] == 1
    assert result.repository == "pypi-proxy-health"
