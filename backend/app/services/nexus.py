import asyncio
import re
from datetime import UTC, datetime
from urllib.parse import unquote

import httpx
from packaging.utils import (
    InvalidSdistFilename,
    InvalidWheelFilename,
    parse_sdist_filename,
    parse_wheel_filename,
)
from packaging.version import InvalidVersion, Version

from app.config import ECOSYSTEM_MAP, settings
from app.schemas import Package, PackageCheckResponse, PackageListResponse, PackageMatch

SEARCH_PATH = "/service/rest/v1/search"
MAX_CHECK_PAGES = 5
MAX_BLOB_PAGES = 20
BLOB_SEARCH_CONCURRENCY = 8


def normalize_pypi_name(name: str) -> str:
    """PEP 503 normalized project name."""
    return re.sub(r"[-_.]+", "-", name).lower()


def _filename_version(filename: str) -> str | None:
    """Extract version from a wheel/sdist filename."""
    name = unquote(filename).split("?", 1)[0].split("#", 1)[0].rsplit("/", 1)[-1]
    try:
        ver = parse_wheel_filename(name)[1]
        return str(ver)
    except (InvalidWheelFilename, ValueError):
        pass
    try:
        ver = parse_sdist_filename(name)[1]
        return str(ver)
    except (InvalidSdistFilename, InvalidVersion, ValueError):
        return None


def simple_index_has_version(html: str, version: str) -> bool:
    """True if PEP 503 simple HTML lists an artifact for the exact version."""
    try:
        want = Version(version)
    except InvalidVersion:
        want = None

    for match in re.finditer(r"""href\s*=\s*["']([^"']+)["']""", html, re.I):
        found = _filename_version(match.group(1))
        if found is None:
            continue
        if found == version:
            return True
        if want is not None:
            try:
                if Version(found) == want:
                    return True
            except InvalidVersion:
                continue
    return False


def _auth() -> httpx.BasicAuth | None:
    if settings.nexus_username and settings.nexus_password:
        return httpx.BasicAuth(settings.nexus_username, settings.nexus_password)
    return None


def _display_name(raw: dict) -> str | None:
    """Compose package name; npm scoped packages use group as @scope."""
    name = raw.get("name")
    if not name:
        return None
    group = (raw.get("group") or "").strip()
    if group and raw.get("format") == "npm":
        scope = group if group.startswith("@") else f"@{group}"
        return f"{scope}/{name}"
    return name


def _map_item(raw: dict) -> Package | None:
    name = _display_name(raw)
    version = raw.get("version")
    if not name or not version:
        return None
    return Package(
        name=name,
        version=version,
        format=raw.get("format", ""),
        repository=raw.get("repository", ""),
    )


async def _fetch_search_page(params: dict[str, str]) -> dict:
    url = f"{settings.nexus_base_url.rstrip('/')}{SEARCH_PATH}"
    async with httpx.AsyncClient(verify=settings.nexus_verify_ssl) as client:
        response = await client.get(url, params=params, auth=_auth(), timeout=30.0)
        response.raise_for_status()
        return response.json()


async def search_packages(
    *,
    repository: str,
    format: str = "",
    q: str = "",
    continuation_token: str | None = None,
) -> PackageListResponse:
    params: dict[str, str] = {"repository": repository}
    if format:
        params["format"] = format
    if q:
        params["q"] = q
    if continuation_token:
        params["continuationToken"] = continuation_token

    data = await _fetch_search_page(params)
    items = [
        pkg for raw in data.get("items", []) if (pkg := _map_item(raw)) is not None
    ]
    return PackageListResponse(
        items=items,
        continuation_token=data.get("continuationToken"),
    )


async def check_package(
    *,
    repository: str,
    package_format: str,
    name: str,
    version: str = "",
    continuation_token: str | None = None,
) -> PackageCheckResponse:
    params: dict[str, str] = {
        "repository": repository,
        "format": package_format,
        "q": name,
    }

    packages_map: dict[str, set[str]] = {}
    next_token: str | None = continuation_token
    pages = 0

    while pages < MAX_CHECK_PAGES:
        page_params = dict(params)
        if next_token:
            page_params["continuationToken"] = next_token

        data = await _fetch_search_page(page_params)
        for raw in data.get("items", []):
            pkg_name = _display_name(raw)
            pkg_version = raw.get("version")
            if pkg_name and pkg_version:
                packages_map.setdefault(pkg_name, set()).add(pkg_version)

        next_token = data.get("continuationToken")
        pages += 1
        if not next_token:
            break

    packages: list[PackageMatch] = []
    version_query = version.lower()
    for pkg_name in sorted(packages_map):
        versions = sorted(packages_map[pkg_name], reverse=True)
        if version_query:
            matched = [v for v in versions if version_query in v.lower()]
            if matched:
                packages.append(PackageMatch(name=pkg_name, versions=matched))
        else:
            packages.append(PackageMatch(name=pkg_name, versions=versions))

    matched_version: str | None = None
    if version_query:
        matched_version = version if packages else None

    return PackageCheckResponse(
        exists=len(packages) > 0,
        query=name,
        format=package_format,
        repository=repository,
        packages=packages,
        matched_version=matched_version,
        continuation_token=next_token,
    )


async def _pypi_json_exists(project: str, version: str) -> bool | None:
    """Query public PyPI JSON API. None = unreachable / untrusted response."""
    base = settings.pypi_json_base_url.rstrip("/")
    url = f"{base}/pypi/{project}/{version}/json"
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, follow_redirects=True)
    except httpx.HTTPError:
        return None
    if response.status_code == 404:
        ctype = response.headers.get("content-type", "")
        return False if "json" in ctype else None
    if not response.is_success:
        return None
    try:
        data = response.json()
    except ValueError:
        return None
    return isinstance(data, dict) and ("info" in data or "urls" in data)


async def _nexus_pypi_simple_has_version(proxy_repo: str, project: str, version: str) -> bool:
    """Use Nexus proxy simple index — remotes to PyPI on cache miss (not local search)."""
    base = settings.nexus_base_url.rstrip("/")
    url = f"{base}/repository/{proxy_repo}/simple/{project}/"
    async with httpx.AsyncClient(verify=settings.nexus_verify_ssl) as client:
        response = await client.get(url, auth=_auth(), timeout=60.0, follow_redirects=True)
        if response.status_code == 404:
            return False
        response.raise_for_status()
        return simple_index_has_version(response.text, version)


async def upstream_version_exists(
    *,
    package_format: str,
    proxy_repo: str,
    name: str,
    version: str,
) -> bool:
    """Check whether name==version exists on the public upstream registry."""
    fmt = package_format.lower()

    if fmt == "pypi":
        project = normalize_pypi_name(name)
        # Prefer public PyPI JSON when reachable and trustworthy.
        if await _pypi_json_exists(project, version) is True:
            return True
        # Corporate networks often cannot reach pypi.org (SSL MITM / block).
        # Nexus proxy /simple/{project}/ remotes to PyPI on cache miss —
        # this is not a local-cache listing search.
        return await _nexus_pypi_simple_has_version(proxy_repo, project, version)

    if fmt == "npm":
        encoded = name.replace("/", "%2F")
        base = settings.npm_registry_base_url.rstrip("/")
        url = f"{base}/{encoded}/{version}"
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(url, follow_redirects=True)
            if response.status_code == 404:
                return await _npm_proxy_has_version(proxy_repo, encoded, version)
            response.raise_for_status()
            return True
        except httpx.HTTPError:
            return await _npm_proxy_has_version(proxy_repo, encoded, version)

    if fmt == "nuget":
        package_id = name.strip().lower()
        ver = version.strip().lower()
        # Prefer public NuGet Gallery flat container when reachable.
        gallery = await _nuget_gallery_has_version(package_id, ver)
        if gallery is True:
            return True
        if gallery is False:
            return False
        # Corporate networks often cannot reach api.nuget.org (SSL MITM / block).
        return await _nuget_proxy_has_version(proxy_repo, package_id, ver)

    raise ValueError(f"Upstream check not implemented for format: {package_format}")


def _nuget_nupkg_path(package_id: str, version: str) -> str:
    """Relative flat-container path for a NuGet package version.

    NuGet protocol requires lowercased id and version in the URL.
    """
    return (
        f"v3-flatcontainer/{package_id}/{version}/{package_id}.{version}.nupkg"
    )


async def _nuget_gallery_has_version(package_id: str, version: str) -> bool | None:
    """Return True/False if Gallery responds; None if unreachable (try proxy)."""
    base = settings.nuget_gallery_base_url.rstrip("/")
    url = f"{base}/{_nuget_nupkg_path(package_id, version)}"
    # 1) honor shared verify setting  2) on SSL/connect failure retry verify=False
    # (corporate MITM often breaks certifi trust for public registries)
    for verify in (settings.nexus_verify_ssl, False):
        try:
            async with httpx.AsyncClient(timeout=30.0, verify=verify) as client:
                response = await client.head(url, follow_redirects=True)
                if response.status_code in (405, 501):
                    response = await client.get(url, follow_redirects=True)
            if response.status_code == 404:
                return False
            response.raise_for_status()
            return True
        except httpx.HTTPError:
            if verify is False:
                return None
            continue
    return None


async def _nuget_proxy_has_version(proxy_repo: str, package_id: str, version: str) -> bool:
    nexus_base = settings.nexus_base_url.rstrip("/")
    nupkg_url = (
        f"{nexus_base}/repository/{proxy_repo}/{_nuget_nupkg_path(package_id, version)}"
    )
    index_url = (
        f"{nexus_base}/repository/{proxy_repo}/v3-flatcontainer/{package_id}/index.json"
    )
    async with httpx.AsyncClient(verify=settings.nexus_verify_ssl) as client:
        response = await client.head(
            nupkg_url, auth=_auth(), timeout=60.0, follow_redirects=True
        )
        if response.status_code in (405, 501):
            response = await client.get(
                nupkg_url, auth=_auth(), timeout=60.0, follow_redirects=True
            )
        if response.status_code == 200:
            return True
        if response.status_code not in (404,):
            try:
                response.raise_for_status()
                return True
            except httpx.HTTPError:
                pass

        # Fallback: flat-container index.json version list (proxy may list without nupkg path)
        idx = await client.get(
            index_url, auth=_auth(), timeout=60.0, follow_redirects=True
        )
        if idx.status_code == 404:
            return False
        idx.raise_for_status()
        try:
            versions = (idx.json() or {}).get("versions") or []
        except ValueError:
            return False
        return version in [str(v).lower() for v in versions]


async def _npm_proxy_has_version(proxy_repo: str, encoded_name: str, version: str) -> bool:
    nexus_base = settings.nexus_base_url.rstrip("/")
    proxy_url = f"{nexus_base}/repository/{proxy_repo}/{encoded_name}"
    async with httpx.AsyncClient(verify=settings.nexus_verify_ssl) as client:
        response = await client.get(
            proxy_url, auth=_auth(), timeout=60.0, follow_redirects=True
        )
        if response.status_code == 404:
            return False
        response.raise_for_status()
        data = response.json()
        versions = data.get("versions") or {}
        return version in versions


def default_hosted_for_format(package_format: str) -> str:
    key = package_format.lower()
    if key in ECOSYSTEM_MAP:
        return ECOSYSTEM_MAP[key].hosted_repo
    return ""


def _parse_blob_created(value: object) -> datetime | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        ts = float(value)
        if ts > 10_000_000_000:
            ts /= 1000
        if ts <= 0:
            return None
        return datetime.fromtimestamp(ts, tz=UTC)
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.isdigit():
        return _parse_blob_created(int(text))
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _iso_from_parsed(parsed: datetime) -> str:
    return parsed.astimezone(UTC).isoformat()


def item_blob_created(raw: dict) -> str | None:
    """Latest blobCreated on a search component (top-level or assets)."""
    assets = raw.get("assets") if isinstance(raw.get("assets"), list) else []
    values: list[object] = [raw.get("blobCreated")]
    values.extend(
        asset.get("blobCreated") for asset in assets if isinstance(asset, dict)
    )
    if not any(_parse_blob_created(v) is not None for v in values):
        values.append(raw.get("lastModified"))
        values.extend(
            asset.get("lastModified") for asset in assets if isinstance(asset, dict)
        )
    candidates: list[datetime] = []
    for value in values:
        parsed = _parse_blob_created(value)
        if parsed is not None:
            candidates.append(parsed)
    if not candidates:
        return None
    return _iso_from_parsed(max(candidates))


def import_name_key(name: str, package_format: str) -> str:
    if package_format == "pypi":
        return normalize_pypi_name(name)
    return name.strip().lower()


def _search_name_params(artifact: str, package_format: str) -> dict[str, str]:
    name = artifact.strip()
    if package_format == "npm" and name.startswith("@") and "/" in name:
        scope, pkg = name[1:].split("/", 1)
        return {"name": pkg, "group": scope}
    return {"q": name}


async def _search_page(
    client: httpx.AsyncClient, params: dict[str, str]
) -> dict:
    url = f"{settings.nexus_base_url.rstrip('/')}{SEARCH_PATH}"
    response = await client.get(
        url, params=params, auth=_auth(), timeout=30.0, follow_redirects=True
    )
    if response.status_code == 404:
        return {"items": []}
    response.raise_for_status()
    return response.json()


async def _blob_created_in_repo(
    client: httpx.AsyncClient,
    *,
    repository: str,
    package_format: str,
    artifact: str,
    wanted_versions: set[str],
) -> dict[tuple[str, str], str]:
    if not wanted_versions:
        return {}
    params = {
        "repository": repository,
        "format": package_format,
        **_search_name_params(artifact, package_format),
    }
    found: dict[tuple[str, str], str] = {}
    token: str | None = None
    name_key = import_name_key(artifact, package_format)
    for _ in range(MAX_BLOB_PAGES):
        page_params = dict(params)
        if token:
            page_params["continuationToken"] = token
        try:
            data = await _search_page(client, page_params)
        except httpx.HTTPError:
            return found
        for raw in data.get("items") or []:
            if not isinstance(raw, dict):
                continue
            display = _display_name(raw) or str(raw.get("name") or "")
            version = str(raw.get("version") or "")
            if not display or not version or version not in wanted_versions:
                continue
            if import_name_key(display, package_format) != name_key:
                continue
            created = item_blob_created(raw)
            if not created:
                continue
            key = (name_key, version)
            previous = found.get(key)
            if previous is None:
                found[key] = created
            else:
                left = _parse_blob_created(previous)
                right = _parse_blob_created(created)
                if right is not None and (left is None or right > left):
                    found[key] = created
        token = data.get("continuationToken")
        if not token:
            break
    return found


async def blob_created_map(
    client: httpx.AsyncClient,
    *,
    hosted_repo: str,
    health_repo: str,
    package_format: str,
    keys: set[tuple[str, str]],
) -> tuple[dict[tuple[str, str], str], set[tuple[str, str]]]:
    """(normalized name, version) → blobCreated, plus keys found in hosted."""
    if not keys:
        return {}, set()
    by_name: dict[str, set[str]] = {}
    for name, version in keys:
        if name and version:
            by_name.setdefault(name, set()).add(version)

    resolved: dict[tuple[str, str], str] = {}
    hosted_keys: set[tuple[str, str]] = set()
    sem = asyncio.Semaphore(BLOB_SEARCH_CONCURRENCY)

    async def lookup(artifact: str, versions: set[str]) -> None:
        async with sem:
            hosted = await _blob_created_in_repo(
                client,
                repository=hosted_repo,
                package_format=package_format,
                artifact=artifact,
                wanted_versions=versions,
            )
            name_key = import_name_key(artifact, package_format)
            hosted_keys.update(hosted.keys())
            missing = {
                ver
                for ver in versions
                if (name_key, ver) not in hosted
            }
            health: dict[tuple[str, str], str] = {}
            if missing and health_repo and health_repo != hosted_repo:
                health = await _blob_created_in_repo(
                    client,
                    repository=health_repo,
                    package_format=package_format,
                    artifact=artifact,
                    wanted_versions=missing,
                )
            resolved.update(hosted)
            resolved.update(health)

    await asyncio.gather(
        *(lookup(name, versions) for name, versions in by_name.items())
    )
    return resolved, hosted_keys
