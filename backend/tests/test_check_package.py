from app.services import nexus


async def test_check_package_partial_version(monkeypatch):
    async def fake_fetch(_params: dict[str, str]) -> dict:
        return {
            "items": [
                {
                    "name": "demo",
                    "version": "17.13.9",
                    "format": "pypi",
                    "group": "",
                    "repository": "pypi-hosted",
                },
                {
                    "name": "demo",
                    "version": "1.0.0",
                    "format": "pypi",
                    "group": "",
                    "repository": "pypi-hosted",
                },
                {
                    "name": "other",
                    "version": "2.0.0",
                    "format": "pypi",
                    "group": "",
                    "repository": "pypi-hosted",
                },
            ],
            "continuationToken": None,
        }

    monkeypatch.setattr(nexus, "_fetch_search_page", fake_fetch)

    result = await nexus.check_package(
        repository="pypi-hosted",
        package_format="pypi",
        name="demo",
        version="13",
    )

    assert result.exists is True
    assert result.matched_version == "13"
    assert len(result.packages) == 1
    assert result.packages[0].name == "demo"
    assert result.packages[0].versions == ["17.13.9"]


async def test_check_package_npm_scoped_name(monkeypatch):
    async def fake_fetch(_params: dict[str, str]) -> dict:
        return {
            "items": [
                {
                    "name": "wasm-util",
                    "version": "0.10.2",
                    "format": "npm",
                    "group": "tybys",
                    "repository": "npm-hosted",
                },
            ],
            "continuationToken": None,
        }

    monkeypatch.setattr(nexus, "_fetch_search_page", fake_fetch)

    result = await nexus.check_package(
        repository="npm-hosted",
        package_format="npm",
        name="wasm-util",
    )

    assert result.packages[0].name == "@tybys/wasm-util"
    assert result.packages[0].versions == ["0.10.2"]


async def test_check_package_no_match(monkeypatch):
    async def fake_fetch(_params: dict[str, str]) -> dict:
        return {"items": [], "continuationToken": None}

    monkeypatch.setattr(nexus, "_fetch_search_page", fake_fetch)

    result = await nexus.check_package(
        repository="pypi-hosted",
        package_format="pypi",
        name="missing-pkg",
        version="1.0.0",
    )

    assert result.exists is False
    assert result.matched_version is None
    assert result.packages == []
