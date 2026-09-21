from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

import httpx

from app.config import settings
from app.schemas import ProxyHealthVulnerability

logger = logging.getLogger(__name__)

ECOSYSTEM_OSV: dict[str, str] = {
    "pypi": "PyPI",
    "npm": "npm",
    "nuget": "NuGet",
}

OSV_TIMEOUT = 60.0
NVD_TIMEOUT = 30.0
QUERY_CONCURRENCY = 8
NVD_CONCURRENCY = 2

_VERSION_PART = re.compile(r"(\d+|\D+)")
_GIT_SHA = re.compile(r"^[0-9a-f]{7,40}$", re.IGNORECASE)
_CVE_ID = re.compile(r"^CVE-\d{4}-\d+$", re.IGNORECASE)
_FALSE_POSITIVE = re.compile(
    r"(오탐|해당\s*없|해당없음|false\s*positive|\bn/?a\b)",
    re.IGNORECASE,
)
# e.g. "fixed in multer 2.4.0", "upgrade to 2.4.0 or later"
_FIXED_IN_TEXT = re.compile(
    r"(?:fixed\s+in|upgrade\s+to)\s+"
    r"(?:(?P<pkg>[@\w./-]+)\s+)?"
    r"v?(?P<ver>\d+(?:\.\d+){0,3})\b",
    re.IGNORECASE,
)


def is_package_fixed_version(value: str | None) -> bool:
    """Reject GIT commit SHAs mistakenly stored as fixed package versions."""
    text = (value or "").strip()
    if not text:
        return False
    if _GIT_SHA.fullmatch(text):
        return False
    return True


def _normalize_published_at(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        return text[:-1] + "+00:00"
    return text


def _published_from_doc(doc: dict[str, Any] | None) -> str | None:
    if not doc:
        return None
    return _normalize_published_at(doc.get("published"))


def _published_from_docs(
    docs: list[dict[str, Any]], *, problem_code: str
) -> str | None:
    want = (problem_code or "").strip().upper()
    for doc in docs:
        if want and want not in _vuln_ids(doc) and str(doc.get("id") or "").upper() != want:
            continue
        got = _published_from_doc(doc)
        if got:
            return got
    for doc in docs:
        got = _published_from_doc(doc)
        if got:
            return got
    return None


def _version_key(value: str) -> tuple:
    parts: list = []
    for token in _VERSION_PART.findall(value.strip()):
        if token.isdigit():
            parts.append((0, int(token)))
        else:
            parts.append((1, token.lower()))
    return tuple(parts)


def _is_newer(candidate: str, current: str) -> bool:
    try:
        return _version_key(candidate) > _version_key(current)
    except Exception:
        return candidate != current


def _version_major(version: str) -> str | None:
    match = re.match(r"^v?(\d+)", (version or "").strip(), re.IGNORECASE)
    return match.group(1) if match else None


def is_resolved_or_false_positive(
    version: str,
    fixed_version: str | None,
    *,
    remark: str | None = None,
) -> bool:
    """True when the listed version is already fixed (정상) or marked 오탐."""
    if remark and _FALSE_POSITIVE.search(remark):
        return True
    text = (fixed_version or "").strip()
    if not text:
        return False
    if _FALSE_POSITIVE.search(text):
        return True
    ver = (version or "").strip()
    if not ver:
        return False
    for part in re.split(r"[,;/|]", text):
        fixed = part.strip()
        if not fixed:
            continue
        if _FALSE_POSITIVE.search(fixed):
            return True
        if not is_package_fixed_version(fixed):
            continue
        maj_f, maj_v = _version_major(fixed), _version_major(ver)
        if maj_f and maj_v and maj_f != maj_v:
            continue
        # version >= fixed → already on the patched line
        if not _is_newer(fixed, ver):
            return True
    return False


def _pick_fixed(current: str, fixed_values: list[str]) -> str | None:
    newer = [f for f in fixed_values if f and _is_newer(f, current)]
    if not newer:
        for f in fixed_values:
            if f:
                return f
        return None
    return min(newer, key=_version_key)


def _vuln_ids(vuln: dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    vid = str(vuln.get("id") or "").strip()
    if vid:
        ids.add(vid.upper())
    for alias in vuln.get("aliases") or []:
        a = str(alias).strip()
        if a:
            ids.add(a.upper())
    return ids


def _ecosystem_fixed_events(
    vuln: dict[str, Any],
    *,
    ecosystem: str,
    package_name: str,
) -> list[str]:
    """Collect semver fixed values; ignore GIT commit SHAs and unnamed ranges."""
    name_key = package_name.lower().strip()
    if not name_key:
        return []
    fixed_values: list[str] = []
    for affected in vuln.get("affected") or []:
        if not isinstance(affected, dict):
            continue
        pkg = affected.get("package") or {}
        if not isinstance(pkg, dict):
            continue
        eco = str(pkg.get("ecosystem") or "").strip()
        pname = str(pkg.get("name") or "").strip()
        if not eco or not pname:
            continue
        if eco != ecosystem:
            continue
        if pname.lower() != name_key:
            continue
        for rng in affected.get("ranges") or []:
            if not isinstance(rng, dict):
                continue
            # GIT ranges use commit SHAs as "fixed"; only package-version ranges.
            if str(rng.get("type") or "").upper() not in {"ECOSYSTEM", "SEMVER"}:
                continue
            for event in rng.get("events") or []:
                if not isinstance(event, dict):
                    continue
                fixed = event.get("fixed")
                if fixed and is_package_fixed_version(str(fixed)):
                    fixed_values.append(str(fixed).strip())
    return fixed_values


def _repo_basename(repo: str) -> str:
    path = (repo or "").rstrip("/").split("/")[-1].lower()
    if path.endswith(".git"):
        path = path[:-4]
    return path


def _package_matches_repo_basename(package_name: str, repo_base: str) -> bool:
    """Match main package or published variants (e.g. pydantic-ai-slim -> pydantic-ai)."""
    name_key = package_name.lower().strip()
    base = repo_base.lower().strip()
    if not name_key or not base:
        return False
    if name_key == base:
        return True
    return name_key.startswith(f"{base}-")


def _range_matches_package(
    *,
    pkg: dict[str, Any],
    rng: dict[str, Any],
    ecosystem: str,
    package_name: str,
) -> bool:
    name_key = package_name.lower().strip()
    if not name_key:
        return False
    eco = str(pkg.get("ecosystem") or "").strip()
    pname = str(pkg.get("name") or "").strip()
    if eco and pname:
        return eco == ecosystem and pname.lower() == name_key
    repo = str(rng.get("repo") or "")
    if not repo:
        return False
    base = _repo_basename(repo)
    return _package_matches_repo_basename(name_key, base)


def _is_stable_version(value: str) -> bool:
    """Skip prereleases like 4.4.1-prerelease.0 when inferring a fix."""
    text = value.strip()
    if not text or not is_package_fixed_version(text):
        return False
    return "-" not in text and "+" not in text


def _extracted_semver_events(
    vuln: dict[str, Any],
    *,
    ecosystem: str,
    package_name: str,
) -> tuple[list[str], list[str]]:
    """Semver from database_specific.extracted_events (CVE GIT CPE mapping)."""
    fixed_values: list[str] = []
    last_affected: list[str] = []
    for affected in vuln.get("affected") or []:
        if not isinstance(affected, dict):
            continue
        pkg = affected.get("package") or {}
        if not isinstance(pkg, dict):
            pkg = {}
        for rng in affected.get("ranges") or []:
            if not isinstance(rng, dict):
                continue
            if not _range_matches_package(
                pkg=pkg, rng=rng, ecosystem=ecosystem, package_name=package_name
            ):
                continue
            ds = rng.get("database_specific") or {}
            if not isinstance(ds, dict):
                continue
            for event in ds.get("extracted_events") or []:
                if not isinstance(event, dict):
                    continue
                fixed = event.get("fixed")
                if fixed and is_package_fixed_version(str(fixed)):
                    fixed_values.append(str(fixed).strip())
                last = event.get("last_affected")
                if last and is_package_fixed_version(str(last)):
                    last_affected.append(str(last).strip())
    return fixed_values, last_affected


def _fixed_from_details_text(
    vuln: dict[str, Any], *, package_name: str
) -> list[str]:
    """Parse advisory text when OSV extracted_events is wrong/incomplete."""
    name_key = package_name.lower().strip()
    blobs = [
        str(vuln.get("summary") or ""),
        str(vuln.get("details") or ""),
    ]
    found: list[str] = []
    for blob in blobs:
        for match in _FIXED_IN_TEXT.finditer(blob):
            pkg = (match.group("pkg") or "").strip().lower()
            ver = (match.group("ver") or "").strip()
            if not ver or not is_package_fixed_version(ver):
                continue
            if pkg:
                pkg_norm = pkg.rstrip(".,;:").lower()
                if name_key and pkg_norm != name_key:
                    continue
            found.append(ver)
    return found


def _fixed_from_vuln(
    vuln: dict[str, Any],
    *,
    ecosystem: str,
    package_name: str,
    current_version: str,
) -> str | None:
    eco_fixed = _ecosystem_fixed_events(
        vuln, ecosystem=ecosystem, package_name=package_name
    )
    picked = _pick_fixed(current_version, eco_fixed)
    if picked:
        return picked
    extracted_fixed, _last = _extracted_semver_events(
        vuln, ecosystem=ecosystem, package_name=package_name
    )
    details_fixed = _fixed_from_details_text(vuln, package_name=package_name)
    # Prefer advisory text when CVE conversion extracted_events is stale/wrong
    # (e.g. multer CVE-2026-88932: extracted 2.3.0 vs details 2.4.0).
    return _pick_fixed(current_version, [*extracted_fixed, *details_fixed])


def _last_affected_from_vulns(
    vulns: list[dict[str, Any]],
    *,
    ecosystem: str,
    package_name: str,
    problem_code: str,
) -> str | None:
    code = (problem_code or "").strip().upper()
    ordered = [v for v in vulns if not code or code in _vuln_ids(v)] or list(vulns)
    lasts: list[str] = []
    for v in ordered:
        _fixed, last = _extracted_semver_events(
            v, ecosystem=ecosystem, package_name=package_name
        )
        lasts.extend(last)
    if not lasts:
        return None
    return max(lasts, key=_version_key)


def _vuln_has_fixed_event(
    vuln: dict[str, Any],
    *,
    ecosystem: str,
    package_name: str,
) -> bool:
    if _ecosystem_fixed_events(vuln, ecosystem=ecosystem, package_name=package_name):
        return True
    fixed, _last = _extracted_semver_events(
        vuln, ecosystem=ecosystem, package_name=package_name
    )
    return bool(fixed)


def _next_published_after(last_affected: str, published: list[str]) -> str | None:
    newer = [
        v
        for v in published
        if _is_stable_version(v) and _is_newer(v, last_affected)
    ]
    if not newer:
        return None
    return min(newer, key=_version_key)


def match_fixed_for_row(
    vulns: list[dict[str, Any]],
    *,
    ecosystem: str,
    artifact: str,
    version: str,
    problem_code: str,
) -> str | None:
    code = (problem_code or "").strip().upper()
    ordered: list[dict[str, Any]] = []
    if code:
        for v in vulns:
            if code in _vuln_ids(v):
                ordered.append(v)
        if not ordered:
            return None
    else:
        ordered = list(vulns)
    # Prefer advisories that publish an explicit fixed event (e.g. GHSA over PYSEC).
    preferred = [
        v
        for v in ordered
        if _vuln_has_fixed_event(v, ecosystem=ecosystem, package_name=artifact)
    ]
    for v in preferred or ordered:
        fixed = _fixed_from_vuln(
            v, ecosystem=ecosystem, package_name=artifact, current_version=version
        )
        if fixed:
            return fixed
    return None


def _related_ids_to_fetch(
    query_vulns: list[dict[str, Any]],
    problem_code: str,
) -> list[str]:
    """GHSA (and CVE) ids to GET when query hits only lack a fixed event."""
    code = (problem_code or "").strip().upper()
    matched = [v for v in query_vulns if code and code in _vuln_ids(v)]
    if not matched and code:
        return [code]

    ordered: list[str] = []
    seen: set[str] = set()

    def add(vid: str) -> None:
        key = vid.strip().upper()
        if not key or key in seen:
            return
        seen.add(key)
        ordered.append(key)

    for v in matched:
        for vid in sorted(_vuln_ids(v)):
            if vid.startswith("GHSA-"):
                add(vid)
    if code:
        add(code)
    return ordered


async def _query_one(
    client: httpx.AsyncClient,
    *,
    osv_eco: str,
    name: str,
    version: str,
    sem: asyncio.Semaphore,
) -> list[dict[str, Any]]:
    base = settings.osv_base_url.rstrip("/")
    payload = {
        "package": {"name": name, "ecosystem": osv_eco},
        "version": version,
    }
    async with sem:
        response = await client.post(
            f"{base}/v1/query",
            json=payload,
            timeout=OSV_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
    if not isinstance(data, dict):
        return []
    raw = data.get("vulns") or []
    if not isinstance(raw, list):
        return []
    return [v for v in raw if isinstance(v, dict)]


async def _fetch_vuln(
    client: httpx.AsyncClient,
    vuln_id: str,
    sem: asyncio.Semaphore,
    cache: dict[str, dict[str, Any] | None],
) -> dict[str, Any] | None:
    key = vuln_id.strip().upper()
    if not key:
        return None
    if key in cache:
        return cache[key]
    base = settings.osv_base_url.rstrip("/")
    try:
        async with sem:
            response = await client.get(
                f"{base}/v1/vulns/{key}",
                timeout=OSV_TIMEOUT,
            )
            if response.status_code == 404:
                cache[key] = None
                return None
            response.raise_for_status()
            data = response.json()
    except Exception as exc:
        logger.warning("OSV vuln fetch failed for %s: %s", key, exc)
        cache[key] = None
        return None
    if not isinstance(data, dict):
        cache[key] = None
        return None
    cache[key] = data
    return data


async def _augment_with_ghsa(
    client: httpx.AsyncClient,
    *,
    query_vulns: list[dict[str, Any]],
    problem_code: str,
    sem: asyncio.Semaphore,
    cache: dict[str, dict[str, Any] | None],
) -> list[dict[str, Any]]:
    """Fetch GHSA (via CVE aliases) when query-only records omit fixed."""
    ids = _related_ids_to_fetch(query_vulns, problem_code)
    if not ids:
        return list(query_vulns)

    extras: list[dict[str, Any]] = []
    seen_docs: set[str] = set()
    for vid in ids:
        doc = await _fetch_vuln(client, vid, sem, cache)
        if not doc:
            continue
        doc_id = str(doc.get("id") or vid).upper()
        if doc_id not in seen_docs:
            seen_docs.add(doc_id)
            extras.append(doc)
        # CVE body may lack fixed; pull GHSA aliases next.
        for alias in sorted(_vuln_ids(doc)):
            if not alias.startswith("GHSA-") or alias in cache:
                continue
            ghsa = await _fetch_vuln(client, alias, sem, cache)
            if not ghsa:
                continue
            ghsa_id = str(ghsa.get("id") or alias).upper()
            if ghsa_id not in seen_docs:
                seen_docs.add(ghsa_id)
                extras.append(ghsa)
    # GHSA/CVE docs first so match prefers explicit fixed events.
    return extras + list(query_vulns)


async def _list_published_versions(
    client: httpx.AsyncClient,
    *,
    osv_eco: str,
    package_name: str,
    sem: asyncio.Semaphore,
    cache: dict[tuple[str, str], list[str] | None],
) -> list[str]:
    key = (osv_eco, package_name.lower().strip())
    if key in cache:
        return cache[key] or []
    name = package_name.strip()
    try:
        async with sem:
            if osv_eco == "npm":
                base = settings.npm_registry_base_url.rstrip("/")
                # scoped: @scope/name -> @scope%2Fname
                enc = name.replace("/", "%2F")
                response = await client.get(f"{base}/{enc}", timeout=OSV_TIMEOUT)
                response.raise_for_status()
                data = response.json()
                versions = list((data.get("versions") or {}).keys())
            elif osv_eco == "PyPI":
                base = settings.pypi_json_base_url.rstrip("/")
                response = await client.get(
                    f"{base}/pypi/{name}/json", timeout=OSV_TIMEOUT
                )
                response.raise_for_status()
                data = response.json()
                versions = list((data.get("releases") or {}).keys())
            else:
                versions = []
    except Exception as exc:
        logger.warning(
            "Registry version list failed for %s/%s: %s", osv_eco, name, exc
        )
        cache[key] = None
        return []
    cache[key] = versions
    return versions


async def _resolve_fixed_from_last_affected(
    client: httpx.AsyncClient,
    *,
    vulns: list[dict[str, Any]],
    osv_eco: str,
    artifact: str,
    version: str,
    problem_code: str,
    sem: asyncio.Semaphore,
    registry_cache: dict[tuple[str, str], list[str] | None],
) -> str | None:
    last = _last_affected_from_vulns(
        vulns,
        ecosystem=osv_eco,
        package_name=artifact,
        problem_code=problem_code,
    )
    if not last:
        return None
    published = await _list_published_versions(
        client,
        osv_eco=osv_eco,
        package_name=artifact,
        sem=sem,
        cache=registry_cache,
    )
    nxt = _next_published_after(last, published)
    if not nxt:
        return None
    # Only suggest an upgrade target; if current already >= nxt keep showing nxt.
    if _is_newer(version, nxt):
        return None
    return nxt


async def _enrich_with_client(
    *,
    verify: bool,
    osv_eco: str,
    vulns: list[ProxyHealthVulnerability],
    query_keys: list[tuple[str, str]],
    key_to_indexes: dict[tuple[str, str], list[int]],
    fixed_by_index: dict[int, str | None],
    published_by_index: dict[int, str | None],
) -> None:
    sem = asyncio.Semaphore(QUERY_CONCURRENCY)
    vuln_cache: dict[str, dict[str, Any] | None] = {}
    registry_cache: dict[tuple[str, str], list[str] | None] = {}
    async with httpx.AsyncClient(verify=verify) as client:

        async def _one(key: tuple[str, str]) -> tuple[tuple[str, str], list[dict[str, Any]]]:
            name, version = key
            try:
                found = await _query_one(
                    client, osv_eco=osv_eco, name=name, version=version, sem=sem
                )
                return key, found
            except Exception as exc:
                logger.warning("OSV query failed for %s@%s: %s", name, version, exc)
                return key, []

        results = await asyncio.gather(*(_one(key) for key in query_keys))

        for key, typed in results:
            for idx in key_to_indexes[key]:
                item = vulns[idx]
                docs = typed
                fixed = match_fixed_for_row(
                    docs,
                    ecosystem=osv_eco,
                    artifact=item.artifact,
                    version=item.version,
                    problem_code=item.problem_code,
                )
                if not fixed and (item.problem_code or "").strip():
                    docs = await _augment_with_ghsa(
                        client,
                        query_vulns=typed,
                        problem_code=item.problem_code,
                        sem=sem,
                        cache=vuln_cache,
                    )
                    fixed = match_fixed_for_row(
                        docs,
                        ecosystem=osv_eco,
                        artifact=item.artifact,
                        version=item.version,
                        problem_code=item.problem_code,
                    )
                if not fixed and (item.problem_code or "").strip():
                    fixed = await _resolve_fixed_from_last_affected(
                        client,
                        vulns=docs,
                        osv_eco=osv_eco,
                        artifact=item.artifact,
                        version=item.version,
                        problem_code=item.problem_code,
                        sem=sem,
                        registry_cache=registry_cache,
                    )
                fixed_by_index[idx] = fixed
                if not published_by_index.get(idx):
                    published_by_index[idx] = _published_from_docs(
                        docs, problem_code=item.problem_code
                    )

        await _fill_missing_published(
            client,
            vulns=vulns,
            published_by_index=published_by_index,
            sem=sem,
            cache=vuln_cache,
        )


def _indexes_needing_published(
    vulns: list[ProxyHealthVulnerability],
    published_by_index: dict[int, str | None],
) -> dict[str, list[int]]:
    need_codes: dict[str, list[int]] = {}
    for i, item in enumerate(vulns):
        if published_by_index.get(i) or item.published_at:
            if item.published_at and not published_by_index.get(i):
                published_by_index[i] = item.published_at
            continue
        code = (item.problem_code or "").strip()
        if not code:
            continue
        need_codes.setdefault(code.upper(), []).append(i)
    return need_codes


async def _fetch_nvd_published(
    client: httpx.AsyncClient,
    cve_id: str,
    sem: asyncio.Semaphore,
    cache: dict[str, str | None],
) -> str | None:
    key = cve_id.strip().upper()
    if not key or not _CVE_ID.fullmatch(key):
        return None
    if key in cache:
        return cache[key]
    if not settings.nvd_enabled:
        cache[key] = None
        return None

    base = settings.nvd_base_url.rstrip("/")
    headers: dict[str, str] = {}
    api_key = (settings.nvd_api_key or "").strip()
    if api_key:
        headers["apiKey"] = api_key
    try:
        async with sem:
            response = await client.get(
                base,
                params={"cveId": key},
                headers=headers,
                timeout=NVD_TIMEOUT,
            )
            if response.status_code == 404:
                cache[key] = None
                return None
            response.raise_for_status()
            data = response.json()
    except Exception as exc:
        logger.warning("NVD CVE fetch failed for %s: %s", key, exc)
        cache[key] = None
        return None

    published: str | None = None
    if isinstance(data, dict):
        items = data.get("vulnerabilities") or []
        if isinstance(items, list) and items:
            first = items[0]
            if isinstance(first, dict):
                cve = first.get("cve")
                if isinstance(cve, dict):
                    published = _normalize_published_at(cve.get("published"))
    cache[key] = published
    return published


async def _fill_missing_published_from_nvd(
    client: httpx.AsyncClient,
    *,
    vulns: list[ProxyHealthVulnerability],
    published_by_index: dict[int, str | None],
) -> None:
    if not settings.nvd_enabled:
        return
    need_codes = _indexes_needing_published(vulns, published_by_index)
    cve_codes = {
        code: indexes
        for code, indexes in need_codes.items()
        if _CVE_ID.fullmatch(code)
    }
    if not cve_codes:
        return

    sem = asyncio.Semaphore(NVD_CONCURRENCY)
    cache: dict[str, str | None] = {}

    async def _one(code: str) -> tuple[str, str | None]:
        return code, await _fetch_nvd_published(client, code, sem, cache)

    fetched = await asyncio.gather(*(_one(code) for code in cve_codes))
    for code, published in fetched:
        if not published:
            continue
        for idx in cve_codes[code]:
            published_by_index[idx] = published


async def _fill_missing_published(
    client: httpx.AsyncClient,
    *,
    vulns: list[ProxyHealthVulnerability],
    published_by_index: dict[int, str | None],
    sem: asyncio.Semaphore,
    cache: dict[str, dict[str, Any] | None],
) -> None:
    need_codes = _indexes_needing_published(vulns, published_by_index)
    if need_codes:

        async def _one(code: str) -> tuple[str, str | None]:
            doc = await _fetch_vuln(client, code, sem, cache)
            return code, _published_from_doc(doc)

        fetched = await asyncio.gather(*(_one(code) for code in need_codes))
        for code, published in fetched:
            if not published:
                continue
            for idx in need_codes[code]:
                published_by_index[idx] = published

    await _fill_missing_published_from_nvd(
        client,
        vulns=vulns,
        published_by_index=published_by_index,
    )


async def enrich_fixed_versions(
    ecosystem: str,
    vulns: list[ProxyHealthVulnerability],
    *,
    skip_override_keys: set[tuple[str, str]] | None = None,
) -> list[ProxyHealthVulnerability]:
    """Attach fixed_version and published_at from OSV (NVD fallback for CVE published)."""
    if not settings.osv_enabled or not vulns:
        return list(vulns)

    osv_eco = ECOSYSTEM_OSV.get(ecosystem.lower().strip())
    if not osv_eco:
        return list(vulns)

    skip = skip_override_keys or set()
    key_to_indexes: dict[tuple[str, str], list[int]] = {}
    query_keys: list[tuple[str, str]] = []
    fixed_by_index: dict[int, str | None] = {}
    published_by_index: dict[int, str | None] = {}
    for i, item in enumerate(vulns):
        published_by_index[i] = item.published_at
        if (item.problem_code, item.artifact) in skip:
            fixed_by_index[i] = item.fixed_version
            continue
        if item.fixed_version and is_package_fixed_version(item.fixed_version):
            fixed_by_index[i] = item.fixed_version
            continue
        name = (item.artifact or "").strip()
        ver = (item.version or "").strip()
        if not name or not ver:
            fixed_by_index[i] = None
            continue
        key = (name, ver)
        if key not in key_to_indexes:
            key_to_indexes[key] = []
            query_keys.append(key)
        key_to_indexes[key].append(i)
        fixed_by_index[i] = None

    # Always attempt published fill (even when fixed versions are already known).
    if not query_keys:
        verify_flags: list[bool] = [bool(settings.osv_verify_ssl)]
        if settings.osv_verify_ssl:
            verify_flags.append(False)
        for verify in verify_flags:
            try:
                sem = asyncio.Semaphore(QUERY_CONCURRENCY)
                cache: dict[str, dict[str, Any] | None] = {}
                async with httpx.AsyncClient(verify=verify) as client:
                    await _fill_missing_published(
                        client,
                        vulns=vulns,
                        published_by_index=published_by_index,
                        sem=sem,
                        cache=cache,
                    )
                break
            except Exception as exc:
                logger.warning(
                    "OSV published fill failed (verify=%s): %s", verify, exc
                )
        return [
            v.model_copy(
                update={
                    "fixed_version": (
                        v.fixed_version
                        if (v.fixed_version and is_package_fixed_version(v.fixed_version))
                        else None
                    ),
                    "published_at": published_by_index.get(i),
                }
            )
            for i, v in enumerate(vulns)
        ]

    verify_flags = [bool(settings.osv_verify_ssl)]
    if settings.osv_verify_ssl:
        verify_flags.append(False)

    last_exc: Exception | None = None
    for verify in verify_flags:
        try:
            await _enrich_with_client(
                verify=verify,
                osv_eco=osv_eco,
                vulns=vulns,
                query_keys=query_keys,
                key_to_indexes=key_to_indexes,
                fixed_by_index=fixed_by_index,
                published_by_index=published_by_index,
            )
            last_exc = None
            break
        except Exception as exc:
            last_exc = exc
            logger.warning("OSV enrichment failed (verify=%s): %s", verify, exc)
    if last_exc is not None:
        logger.warning("OSV enrichment skipped after retries: %s", last_exc)

    return [
        v.model_copy(
            update={
                "fixed_version": fixed_by_index.get(i),
                "published_at": published_by_index.get(i),
            }
        )
        for i, v in enumerate(vulns)
    ]
