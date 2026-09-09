import pytest
from app.schemas import ProxyHealthVulnerability
from app.services.osv import enrich_fixed_versions, match_fixed_for_row

SAMPLE_VULN = {
    "id": "GHSA-xxxx",
    "aliases": ["CVE-2020-1"],
    "published": "2020-01-15T00:00:00Z",
    "affected": [
        {
            "package": {"ecosystem": "PyPI", "name": "foo"},
            "ranges": [
                {
                    "type": "ECOSYSTEM",
                    "events": [
                        {"introduced": "0"},
                        {"fixed": "1.2.0"},
                        {"fixed": "1.5.0"},
                    ],
                }
            ],
        }
    ],
}

# onnx-style: version query returns PYSEC (no fixed); GHSA has fixed.
PYSEC_NO_FIXED = {
    "id": "PYSEC-2025-148",
    "aliases": ["CVE-2025-51480", "GHSA-6rq9-53c3-f7vj"],
    "affected": [
        {
            "package": {"ecosystem": "PyPI", "name": "onnx"},
            "ranges": [
                {
                    "type": "ECOSYSTEM",
                    "events": [
                        {"introduced": "0"},
                        {"last_affected": "1.17.0"},
                    ],
                }
            ],
        }
    ],
}

GHSA_WITH_FIXED = {
    "id": "GHSA-6rq9-53c3-f7vj",
    "aliases": ["CVE-2024-5187", "CVE-2025-51480", "PYSEC-2025-148"],
    "affected": [
        {
            "package": {"ecosystem": "PyPI", "name": "onnx"},
            "ranges": [
                {
                    "type": "ECOSYSTEM",
                    "events": [
                        {"introduced": "0"},
                        {"fixed": "1.16.2"},
                    ],
                }
            ],
        }
    ],
}


def test_match_fixed_prefers_cve_alias_and_min_newer():
    fixed = match_fixed_for_row(
        [SAMPLE_VULN],
        ecosystem="PyPI",
        artifact="foo",
        version="1.0.0",
        problem_code="CVE-2020-1",
    )
    assert fixed == "1.2.0"


def test_match_fixed_without_code_still_works():
    fixed = match_fixed_for_row(
        [SAMPLE_VULN],
        ecosystem="PyPI",
        artifact="foo",
        version="1.0.0",
        problem_code="",
    )
    assert fixed == "1.2.0"


def test_match_fixed_prefers_ghsa_over_pysec_without_fixed():
    fixed = match_fixed_for_row(
        [PYSEC_NO_FIXED, GHSA_WITH_FIXED],
        ecosystem="PyPI",
        artifact="onnx",
        version="1.16.1",
        problem_code="CVE-2025-51480",
    )
    assert fixed == "1.16.2"


def test_match_fixed_pysec_alone_has_no_fixed():
    fixed = match_fixed_for_row(
        [PYSEC_NO_FIXED],
        ecosystem="PyPI",
        artifact="onnx",
        version="1.16.1",
        problem_code="CVE-2025-51480",
    )
    assert fixed is None


def test_match_fixed_ignores_git_commit_sha():
    """CVE-style GIT fixed commits must not appear as package versions."""
    cve_git = {
        "id": "CVE-2026-78207",
        "aliases": ["GHSA-qwr4-7h29-chpf"],
        "affected": [
            {
                "ranges": [
                    {
                        "type": "GIT",
                        "repo": "https://github.com/mateocallec/exceljs-hardened",
                        "events": [
                            {"introduced": "0"},
                            {
                                "fixed": "37149551343c6305aa8aca4f43567c1091102287"
                            },
                        ],
                    }
                ]
            }
        ],
    }
    fixed = match_fixed_for_row(
        [cve_git],
        ecosystem="npm",
        artifact="exceljs",
        version="4.4.0",
        problem_code="CVE-2026-78207",
    )
    assert fixed is None


def test_is_package_fixed_version_rejects_sha():
    from app.services.osv import is_package_fixed_version

    assert is_package_fixed_version("4.4.1") is True
    assert (
        is_package_fixed_version("37149551343c6305aa8aca4f43567c1091102287") is False
    )
    assert is_package_fixed_version("abc1234") is False


def test_is_resolved_or_false_positive():
    from app.services.osv import is_resolved_or_false_positive

    assert is_resolved_or_false_positive("1.2.0", "1.2.0") is True
    assert is_resolved_or_false_positive("2.1.0", "2.0.0") is True
    assert is_resolved_or_false_positive("1.0.0", "1.2.0") is False
    assert is_resolved_or_false_positive("2.0.0", "1.2.0") is False  # other major
    assert is_resolved_or_false_positive("1.0.0", None, remark="오탐") is True
    assert is_resolved_or_false_positive("1.0.0", "오탐") is True
    assert is_resolved_or_false_positive("1.5.0", "1.2.0, 2.1.0") is True


def test_match_uses_extracted_events_fixed_when_repo_matches():
    cve = {
        "id": "CVE-TEST",
        "aliases": ["CVE-TEST"],
        "affected": [
            {
                "ranges": [
                    {
                        "type": "GIT",
                        "repo": "https://github.com/example/foo",
                        "events": [{"introduced": "0"}, {"last_affected": "abc"}],
                        "database_specific": {
                            "extracted_events": [
                                {"introduced": "0"},
                                {"fixed": "1.2.3"},
                            ]
                        },
                    }
                ]
            }
        ],
    }
    fixed = match_fixed_for_row(
        [cve],
        ecosystem="npm",
        artifact="foo",
        version="1.0.0",
        problem_code="CVE-TEST",
    )
    assert fixed == "1.2.3"


def test_match_uses_extracted_events_fixed_for_slim_variant_repo():
    cve = {
        "id": "CVE-2026-65975",
        "aliases": ["CVE-2026-65975", "GHSA-jpr8-2v3g-wgf9"],
        "affected": [
            {
                "ranges": [
                    {
                        "type": "GIT",
                        "repo": "https://github.com/pydantic/pydantic-ai",
                        "database_specific": {
                            "extracted_events": [
                                {"introduced": "1.88.0"},
                                {"fixed": "1.107.1"},
                                {"introduced": "2.0.0"},
                                {"fixed": "2.5.0"},
                            ]
                        },
                    }
                ]
            }
        ],
    }
    fixed = match_fixed_for_row(
        [cve],
        ecosystem="PyPI",
        artifact="pydantic-ai-slim",
        version="1.106.0",
        problem_code="CVE-2026-65975",
    )
    assert fixed == "1.107.1"


def test_match_fixed_ignores_unrelated_vulns_when_code_missing_from_query():
    other = {
        "id": "CVE-OTHER",
        "affected": [
            {
                "package": {"ecosystem": "PyPI", "name": "pydantic-ai-slim"},
                "ranges": [
                    {
                        "type": "ECOSYSTEM",
                        "events": [{"introduced": "0"}, {"fixed": "1.106.0"}],
                    }
                ],
            }
        ],
    }
    fixed = match_fixed_for_row(
        [other],
        ecosystem="PyPI",
        artifact="pydantic-ai-slim",
        version="1.102.0",
        problem_code="CVE-2026-65975",
    )
    assert fixed is None


def test_match_ignores_extracted_fixed_for_unrelated_fork_repo():
    cve = {
        "id": "CVE-2026-78207",
        "affected": [
            {
                "ranges": [
                    {
                        "type": "GIT",
                        "repo": "https://github.com/mateocallec/exceljs-hardened",
                        "events": [{"introduced": "0"}, {"fixed": "deadbeef"}],
                        "database_specific": {
                            "extracted_events": [
                                {"introduced": "0"},
                                {"fixed": "5.0.0"},
                            ]
                        },
                    }
                ]
            }
        ],
    }
    fixed = match_fixed_for_row(
        [cve],
        ecosystem="npm",
        artifact="exceljs",
        version="4.4.0",
        problem_code="CVE-2026-78207",
    )
    assert fixed is None


def test_next_published_after_skips_prerelease():
    from app.services.osv import _next_published_after

    assert (
        _next_published_after("0.8.2", ["0.8.2", "0.8.3", "0.9.0-beta.1"]) == "0.8.3"
    )
    assert _next_published_after("4.4.0", ["4.4.0", "4.4.1-prerelease.0"]) is None


@pytest.mark.asyncio
async def test_enrich_disabled_sets_null(monkeypatch):
    monkeypatch.setattr("app.services.osv.settings.osv_enabled", False)
    rows = [
        ProxyHealthVulnerability(
            threat_level=8.0,
            problem_code="CVE-2020-1",
            artifact="foo",
            version="1.0.0",
        )
    ]
    out = await enrich_fixed_versions("pypi", rows)
    assert out[0].fixed_version is None


@pytest.mark.asyncio
async def test_enrich_uses_query_and_sets_fixed(monkeypatch):
    monkeypatch.setattr("app.services.osv.settings.osv_enabled", True)
    monkeypatch.setattr("app.services.osv.settings.osv_base_url", "https://osv.test")
    monkeypatch.setattr("app.services.osv.settings.osv_verify_ssl", False)
    monkeypatch.setattr("app.services.osv.settings.nvd_enabled", False)

    class _Resp:
        def __init__(self, status_code: int, data):
            self.status_code = status_code
            self._data = data

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(f"http {self.status_code}")

        def json(self):
            return self._data

    class _Client:
        def __init__(self, *a, **k):
            assert k.get("verify") is False

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, timeout=None):
            assert url.endswith("/v1/query")
            return _Resp(200, {"vulns": [SAMPLE_VULN]})

    monkeypatch.setattr("app.services.osv.httpx.AsyncClient", _Client)
    rows = [
        ProxyHealthVulnerability(
            threat_level=8.0,
            problem_code="CVE-2020-1",
            artifact="foo",
            version="1.0.0",
        )
    ]
    out = await enrich_fixed_versions("pypi", rows)
    assert out[0].fixed_version == "1.2.0"
    assert out[0].published_at == "2020-01-15T00:00:00+00:00"


@pytest.mark.asyncio
async def test_enrich_skips_rows_with_existing_fixed(monkeypatch):
    monkeypatch.setattr("app.services.osv.settings.osv_enabled", True)
    monkeypatch.setattr("app.services.osv.settings.osv_base_url", "https://osv.test")
    monkeypatch.setattr("app.services.osv.settings.osv_verify_ssl", False)
    monkeypatch.setattr("app.services.osv.settings.nvd_enabled", False)
    calls = {"post": 0, "get": 0}

    class _Resp:
        def __init__(self, status_code: int, data):
            self.status_code = status_code
            self._data = data

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(f"http {self.status_code}")

        def json(self):
            return self._data

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **k):
            calls["post"] += 1
            raise AssertionError("should not query OSV when fixed exists")

        async def get(self, url, timeout=None):
            calls["get"] += 1
            assert "/v1/vulns/" in url
            return _Resp(
                200,
                {"id": "CVE-2020-1", "published": "2020-02-01T12:00:00Z"},
            )

    monkeypatch.setattr("app.services.osv.httpx.AsyncClient", _Client)
    rows = [
        ProxyHealthVulnerability(
            threat_level=8.0,
            problem_code="CVE-2020-1",
            artifact="foo",
            version="1.0.0",
            fixed_version="1.2.0",
        )
    ]
    out = await enrich_fixed_versions("pypi", rows)
    assert out[0].fixed_version == "1.2.0"
    assert out[0].published_at == "2020-02-01T12:00:00+00:00"
    assert calls["post"] == 0
    assert calls["get"] == 1


@pytest.mark.asyncio
async def test_enrich_osv_failure_keeps_null(monkeypatch):
    monkeypatch.setattr("app.services.osv.settings.osv_enabled", True)
    monkeypatch.setattr("app.services.osv.settings.osv_verify_ssl", False)
    monkeypatch.setattr("app.services.osv.settings.nvd_enabled", False)

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **k):
            raise RuntimeError("network down")

    monkeypatch.setattr("app.services.osv.httpx.AsyncClient", _Client)
    rows = [
        ProxyHealthVulnerability(
            threat_level=8.0,
            problem_code="CVE-2020-1",
            artifact="foo",
            version="1.0.0",
        )
    ]
    out = await enrich_fixed_versions("pypi", rows)
    assert out[0].fixed_version is None


@pytest.mark.asyncio
async def test_enrich_fetches_ghsa_when_query_pysec_lacks_fixed(monkeypatch):
    monkeypatch.setattr("app.services.osv.settings.osv_enabled", True)
    monkeypatch.setattr("app.services.osv.settings.osv_base_url", "https://osv.test")
    monkeypatch.setattr("app.services.osv.settings.osv_verify_ssl", False)
    monkeypatch.setattr("app.services.osv.settings.nvd_enabled", False)
    gets: list[str] = []

    class _Resp:
        def __init__(self, status_code: int, data):
            self.status_code = status_code
            self._data = data

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(f"http {self.status_code}")

        def json(self):
            return self._data

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, timeout=None):
            assert url.endswith("/v1/query")
            return _Resp(200, {"vulns": [PYSEC_NO_FIXED]})

        async def get(self, url, timeout=None):
            gets.append(url)
            if url.endswith("/v1/vulns/GHSA-6RQ9-53C3-F7VJ"):
                return _Resp(200, GHSA_WITH_FIXED)
            if url.endswith("/v1/vulns/CVE-2025-51480"):
                return _Resp(
                    200,
                    {
                        "id": "CVE-2025-51480",
                        "aliases": ["GHSA-6rq9-53c3-f7vj"],
                        "affected": [],
                    },
                )
            return _Resp(404, {})

    monkeypatch.setattr("app.services.osv.httpx.AsyncClient", _Client)
    rows = [
        ProxyHealthVulnerability(
            threat_level=7.5,
            problem_code="CVE-2025-51480",
            artifact="onnx",
            version="1.16.1",
        )
    ]
    out = await enrich_fixed_versions("pypi", rows)
    assert out[0].fixed_version == "1.16.2"
    assert any("GHSA-6RQ9-53C3-F7VJ" in u for u in gets)


FFLATE_CVE = {
    "id": "CVE-2026-45820",
    "aliases": [],
    "affected": [
        {
            "ranges": [
                {
                    "type": "GIT",
                    "repo": "https://github.com/101arrowz/fflate",
                    "events": [
                        {"introduced": "0"},
                        {"last_affected": "d3243651cb142e3e04f3e4bc037b9e985878f444"},
                    ],
                    "database_specific": {
                        "extracted_events": [
                            {"introduced": "0"},
                            {"last_affected": "0.8.2"},
                        ]
                    },
                }
            ]
        }
    ],
}


@pytest.mark.asyncio
async def test_enrich_infers_fix_from_last_affected_via_registry(monkeypatch):
    monkeypatch.setattr("app.services.osv.settings.osv_enabled", True)
    monkeypatch.setattr("app.services.osv.settings.osv_base_url", "https://osv.test")
    monkeypatch.setattr("app.services.osv.settings.osv_verify_ssl", False)
    monkeypatch.setattr("app.services.osv.settings.nvd_enabled", False)
    monkeypatch.setattr(
        "app.services.osv.settings.npm_registry_base_url", "https://registry.test"
    )

    class _Resp:
        def __init__(self, status_code: int, data):
            self.status_code = status_code
            self._data = data

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(f"http {self.status_code}")

        def json(self):
            return self._data

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, timeout=None):
            return _Resp(200, {"vulns": []})

        async def get(self, url, timeout=None):
            if url.endswith("/v1/vulns/CVE-2026-45820"):
                return _Resp(200, FFLATE_CVE)
            if "registry.test/fflate" in url:
                return _Resp(
                    200,
                    {"versions": {"0.8.1": {}, "0.8.2": {}, "0.8.3": {}}},
                )
            return _Resp(404, {})

    monkeypatch.setattr("app.services.osv.httpx.AsyncClient", _Client)
    rows = [
        ProxyHealthVulnerability(
            threat_level=6.0,
            problem_code="CVE-2026-45820",
            artifact="fflate",
            version="0.8.2",
        )
    ]
    out = await enrich_fixed_versions("npm", rows)
    assert out[0].fixed_version == "0.8.3"


@pytest.mark.asyncio
async def test_enrich_published_falls_back_to_nvd_when_osv_missing(monkeypatch):
    monkeypatch.setattr("app.services.osv.settings.osv_enabled", True)
    monkeypatch.setattr("app.services.osv.settings.osv_base_url", "https://osv.test")
    monkeypatch.setattr("app.services.osv.settings.osv_verify_ssl", False)
    monkeypatch.setattr("app.services.osv.settings.nvd_enabled", True)
    monkeypatch.setattr(
        "app.services.osv.settings.nvd_base_url",
        "https://nvd.test/rest/json/cves/2.0",
    )
    monkeypatch.setattr("app.services.osv.settings.nvd_api_key", "test-key")
    nvd_calls: list[dict] = []

    class _Resp:
        def __init__(self, status_code: int, data):
            self.status_code = status_code
            self._data = data

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(f"http {self.status_code}")

        def json(self):
            return self._data

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, timeout=None, params=None, headers=None):
            if "/v1/vulns/" in url:
                return _Resp(404, {"code": 5, "message": "Vulnerability not found"})
            if "nvd.test" in url:
                nvd_calls.append({"params": params, "headers": headers or {}})
                assert params == {"cveId": "CVE-2026-50653"}
                assert headers.get("apiKey") == "test-key"
                return _Resp(
                    200,
                    {
                        "vulnerabilities": [
                            {
                                "cve": {
                                    "id": "CVE-2026-50653",
                                    "published": "2026-07-14T20:37:40.854",
                                }
                            }
                        ]
                    },
                )
            return _Resp(404, {})

    monkeypatch.setattr("app.services.osv.httpx.AsyncClient", _Client)
    rows = [
        ProxyHealthVulnerability(
            threat_level=7.5,
            problem_code="CVE-2026-50653",
            artifact="Azure.Identity",
            version="1.0.0",
            fixed_version="1.1.0",
        )
    ]
    out = await enrich_fixed_versions("nuget", rows)
    assert out[0].published_at == "2026-07-14T20:37:40.854"
    assert len(nvd_calls) == 1


@pytest.mark.asyncio
async def test_enrich_prefers_osv_published_over_nvd(monkeypatch):
    monkeypatch.setattr("app.services.osv.settings.osv_enabled", True)
    monkeypatch.setattr("app.services.osv.settings.osv_base_url", "https://osv.test")
    monkeypatch.setattr("app.services.osv.settings.osv_verify_ssl", False)
    monkeypatch.setattr("app.services.osv.settings.nvd_enabled", True)
    monkeypatch.setattr(
        "app.services.osv.settings.nvd_base_url",
        "https://nvd.test/rest/json/cves/2.0",
    )
    nvd_hits = {"count": 0}

    class _Resp:
        def __init__(self, status_code: int, data):
            self.status_code = status_code
            self._data = data

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(f"http {self.status_code}")

        def json(self):
            return self._data

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, timeout=None, params=None, headers=None):
            if "/v1/vulns/" in url:
                return _Resp(
                    200,
                    {"id": "CVE-2020-1", "published": "2020-02-01T12:00:00Z"},
                )
            if "nvd.test" in url:
                nvd_hits["count"] += 1
                return _Resp(
                    200,
                    {
                        "vulnerabilities": [
                            {"cve": {"published": "2019-01-01T00:00:00.000"}}
                        ]
                    },
                )
            return _Resp(404, {})

    monkeypatch.setattr("app.services.osv.httpx.AsyncClient", _Client)
    rows = [
        ProxyHealthVulnerability(
            threat_level=8.0,
            problem_code="CVE-2020-1",
            artifact="foo",
            version="1.0.0",
            fixed_version="1.2.0",
        )
    ]
    out = await enrich_fixed_versions("pypi", rows)
    assert out[0].published_at == "2020-02-01T12:00:00+00:00"
    assert nvd_hits["count"] == 0


@pytest.mark.asyncio
async def test_enrich_skips_nvd_for_non_cve_codes(monkeypatch):
    monkeypatch.setattr("app.services.osv.settings.osv_enabled", True)
    monkeypatch.setattr("app.services.osv.settings.osv_base_url", "https://osv.test")
    monkeypatch.setattr("app.services.osv.settings.osv_verify_ssl", False)
    monkeypatch.setattr("app.services.osv.settings.nvd_enabled", True)
    monkeypatch.setattr(
        "app.services.osv.settings.nvd_base_url",
        "https://nvd.test/rest/json/cves/2.0",
    )
    nvd_hits = {"count": 0}

    class _Resp:
        def __init__(self, status_code: int, data):
            self.status_code = status_code
            self._data = data

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(f"http {self.status_code}")

        def json(self):
            return self._data

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, timeout=None, params=None, headers=None):
            if "/v1/vulns/" in url:
                return _Resp(404, {})
            if "nvd.test" in url:
                nvd_hits["count"] += 1
            return _Resp(404, {})

    monkeypatch.setattr("app.services.osv.httpx.AsyncClient", _Client)
    rows = [
        ProxyHealthVulnerability(
            threat_level=5.0,
            problem_code="GHSA-xxxx-yyyy-zzzz",
            artifact="foo",
            version="1.0.0",
            fixed_version="1.1.0",
        )
    ]
    out = await enrich_fixed_versions("pypi", rows)
    assert out[0].published_at is None
    assert nvd_hits["count"] == 0
