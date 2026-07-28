from app.services.nexus import (
    _display_name,
    _map_item,
    default_hosted_for_format,
    normalize_pypi_name,
    simple_index_has_version,
    upstream_version_exists,
)
import httpx
import pytest


def test_normalize_pypi_name():
    assert normalize_pypi_name("Requests") == "requests"
    assert normalize_pypi_name("my_package") == "my-package"
    assert normalize_pypi_name("my.package") == "my-package"


def test_simple_index_has_version_exact():
    html = """
    <a href="../../packages/uv/0.11.1/uv-0.11.1-py3-none-any.whl#sha256=abc">uv-0.11.1</a>
    <a href="../../packages/uv/0.11.17/uv-0.11.17-py3-none-any.whl#sha256=def">uv-0.11.17</a>
    """
    assert simple_index_has_version(html, "0.11.17") is True
    assert simple_index_has_version(html, "0.11.1") is True
    assert simple_index_has_version(html, "0.11") is False
    assert simple_index_has_version(html, "9.9.9") is False


@pytest.mark.asyncio
async def test_upstream_version_exists_pypi_json_ok(monkeypatch):
    class _Resp:
        status_code = 200
        is_success = True
        headers = {"content-type": "application/json"}

        def json(self):
            return {"info": {"version": "2.32.3"}, "urls": []}

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url, timeout=None, follow_redirects=None, auth=None):
            assert "pypi.org/pypi/requests/2.32.3/json" in url
            return _Resp()

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    assert (
        await upstream_version_exists(
            package_format="pypi",
            proxy_repo="pypi-proxy",
            name="Requests",
            version="2.32.3",
        )
        is True
    )


@pytest.mark.asyncio
async def test_upstream_version_exists_falls_back_to_simple(monkeypatch):
    class _FailClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url, timeout=None, follow_redirects=None, auth=None):
            if "pypi.org" in url:
                raise httpx.ConnectError("ssl")

            class _Resp:
                status_code = 200
                text = (
                    '<a href="uv-0.11.17-py3-none-any.whl#sha256=abc">'
                    "uv-0.11.17-py3-none-any.whl</a>"
                )

                def raise_for_status(self):
                    return None

            assert "pypi-proxy/simple/uv/" in url
            return _Resp()

    monkeypatch.setattr(httpx, "AsyncClient", _FailClient)
    assert (
        await upstream_version_exists(
            package_format="pypi",
            proxy_repo="pypi-proxy",
            name="uv",
            version="0.11.17",
        )
        is True
    )


@pytest.mark.asyncio
async def test_upstream_version_exists_pypi_missing(monkeypatch):
    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url, timeout=None, follow_redirects=None, auth=None):
            if "pypi.org" in url:

                class _Json404:
                    status_code = 404
                    is_success = False
                    headers = {"content-type": "application/json"}

                return _Json404()

            class _Simple:
                status_code = 200
                text = '<a href="requests-2.32.3-py3-none-any.whl">x</a>'

                def raise_for_status(self):
                    return None

            return _Simple()

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    assert (
        await upstream_version_exists(
            package_format="pypi",
            proxy_repo="pypi-proxy",
            name="requests",
            version="99.99.99",
        )
        is False
    )


def test_display_name_npm_scoped():
    assert (
        _display_name({"name": "wasm-util", "group": "tybys", "format": "npm"})
        == "@tybys/wasm-util"
    )


def test_display_name_npm_group_already_scoped():
    assert (
        _display_name({"name": "wasm-util", "group": "@tybys", "format": "npm"})
        == "@tybys/wasm-util"
    )


def test_display_name_pypi_ignores_group():
    assert _display_name({"name": "requests", "group": "", "format": "pypi"}) == "requests"


def test_display_name_missing_name():
    assert _display_name({"group": "tybys", "format": "npm"}) is None


def test_map_item_requires_version():
    assert _map_item({"name": "uv", "format": "pypi", "group": ""}) is None


def test_map_item_ok():
    pkg = _map_item(
        {
            "name": "uv",
            "version": "0.11.7",
            "format": "pypi",
            "repository": "pypi-hosted",
            "group": "",
        }
    )
    assert pkg is not None
    assert pkg.name == "uv"
    assert pkg.version == "0.11.7"


def test_default_hosted_for_format():
    assert default_hosted_for_format("pypi") == "pypi-hosted"
    assert default_hosted_for_format("NPM") == "npm-hosted"
    assert default_hosted_for_format("nuget") == "nuget-hosted"
    assert default_hosted_for_format("unknown") == ""


@pytest.mark.asyncio
async def test_upstream_version_exists_nuget_gallery_ok(monkeypatch):
    class _Resp:
        status_code = 200

        def raise_for_status(self):
            return None

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def head(self, url, timeout=None, follow_redirects=None, auth=None):
            assert "api.nuget.org/v3-flatcontainer/microsoft.build/18.8.2/" in url
            assert url.endswith("microsoft.build.18.8.2.nupkg")
            return _Resp()

        async def get(self, url, timeout=None, follow_redirects=None, auth=None):
            raise AssertionError("GET should not be needed when HEAD succeeds")

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    assert (
        await upstream_version_exists(
            package_format="nuget",
            proxy_repo="nuget-proxy",
            name="Microsoft.Build",
            version="18.8.2",
        )
        is True
    )


@pytest.mark.asyncio
async def test_upstream_version_exists_nuget_gallery_404(monkeypatch):
    class _Resp:
        status_code = 404

        def raise_for_status(self):
            raise httpx.HTTPStatusError("404", request=None, response=self)

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def head(self, url, timeout=None, follow_redirects=None, auth=None):
            return _Resp()

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    assert (
        await upstream_version_exists(
            package_format="nuget",
            proxy_repo="nuget-proxy",
            name="Missing.Package",
            version="9.9.9",
        )
        is False
    )


@pytest.mark.asyncio
async def test_upstream_version_exists_nuget_ssl_retries_verify_false(monkeypatch):
    calls: list[bool | None] = []

    class _Resp:
        status_code = 200

        def raise_for_status(self):
            return None

    class _Client:
        def __init__(self, *args, **kwargs):
            self.verify = kwargs.get("verify", True)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def head(self, url, timeout=None, follow_redirects=None, auth=None):
            calls.append(self.verify)
            if self.verify is not False:
                raise httpx.ConnectError("ssl")
            return _Resp()

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    assert (
        await upstream_version_exists(
            package_format="nuget",
            proxy_repo="nuget-proxy",
            name="Microsoft.Build",
            version="17.14.28",
        )
        is True
    )
    assert True in calls or calls[0] is True
    assert False in calls


@pytest.mark.asyncio
async def test_upstream_version_exists_nuget_falls_back_to_proxy(monkeypatch):
    class _ProxyResp:
        status_code = 200

        def raise_for_status(self):
            return None

    class _Client:
        def __init__(self, *args, **kwargs):
            self._verify = kwargs.get("verify")

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def head(self, url, timeout=None, follow_redirects=None, auth=None):
            if "api.nuget.org" in url:
                raise httpx.ConnectError("ssl")
            assert "repository/nuget-proxy/v3-flatcontainer/" in url
            assert "newtonsoft.json/13.0.3/" in url
            return _ProxyResp()

        async def get(self, url, timeout=None, follow_redirects=None, auth=None):
            raise AssertionError("GET should not be needed when HEAD succeeds")

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    # Both verify=True and verify=False gallery attempts fail with ConnectError → proxy
    assert (
        await upstream_version_exists(
            package_format="nuget",
            proxy_repo="nuget-proxy",
            name="Newtonsoft.Json",
            version="13.0.3",
        )
        is True
    )
