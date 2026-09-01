from datetime import UTC, datetime
from typing import Any

import httpx

from app.config import ECOSYSTEM_MAP, EcosystemConfig, settings
from app.schemas import (
    ProxyHealthLicense,
    ProxyHealthResponse,
    ProxyHealthVulnerability,
)
from app.services.nexus import (
    _auth,
    blob_created_map,
    import_name_key,
)

META_PATH = "/service/rest/internal/ui/healthcheck/{repo}"
DETAIL_JSON = {
    "security": "security.json",
    "licenses": "licenses.json",
}


class ProxyHealthUnavailable(Exception):
    """RHC detail report could not be loaded for any candidate repository."""


def _join_licenses(values: Any) -> str:
    if not values:
        return ""
    if isinstance(values, str):
        return values
    if isinstance(values, list):
        return ", ".join(str(v) for v in values if v)
    return str(values)


def _coordinates(raw: dict) -> dict:
    ident = raw.get("componentIdentifier") or {}
    coords = ident.get("coordinates") or {}
    return coords if isinstance(coords, dict) else {}


def _artifact_version(raw: dict) -> tuple[str, str, str]:
    coords = _coordinates(raw)
    artifact = (
        coords.get("packageId")
        or coords.get("name")
        or raw.get("artifactId")
        or ""
    )
    version = coords.get("version") or raw.get("version") or ""
    group = raw.get("groupId") or coords.get("group") or coords.get("groupId") or ""
    return str(group or ""), str(artifact or ""), str(version or "")


def _cve_url(raw: dict, problem_code: str) -> str:
    url = raw.get("url")
    if isinstance(url, str) and url.strip():
        return url.strip()
    if problem_code.upper().startswith("CVE-"):
        return f"https://cve.mitre.org/cgi-bin/cvename.cgi?name={problem_code}"
    return ""


def map_vulnerability(raw: dict) -> ProxyHealthVulnerability | None:
    group, artifact, version = _artifact_version(raw)
    problem = (
        raw.get("reference")
        or (raw.get("vulnIds") or [None])[0]
        or raw.get("problem_code")
        or ""
    )
    problem_code = str(problem).strip()
    if not artifact and not problem_code:
        return None
    score = raw.get("score")
    threat: float | None
    try:
        threat = float(score) if score is not None else None
    except (TypeError, ValueError):
        threat = None
    return ProxyHealthVulnerability(
        threat_level=threat,
        problem_code=problem_code,
        problem_url=_cve_url(raw, problem_code),
        group=group,
        artifact=artifact,
        version=version,
    )


def map_license(raw: dict) -> ProxyHealthLicense | None:
    group, artifact, version = _artifact_version(raw)
    if not artifact:
        return None
    counters = raw.get("securityCounters") or {}
    security_issues = None
    if isinstance(counters, dict):
        security_issues = sum(
            int(counters.get(key, 0) or 0)
            for key in ("Critical", "Severe", "Moderate")
        )
    return ProxyHealthLicense(
        license_threat=str(raw.get("effectiveLicenseThreat") or ""),
        declared_license=_join_licenses(raw.get("declaredLicenses")),
        observed_licenses=_join_licenses(raw.get("observedLicenses")),
        group=group,
        artifact=artifact,
        version=version,
        security_issues=security_issues,
    )


def _aa_data(payload: Any) -> list[dict]:
    if isinstance(payload, dict):
        items = payload.get("aaData") or payload.get("data") or []
    elif isinstance(payload, list):
        items = payload
    else:
        items = []
    return [item for item in items if isinstance(item, dict)]


def _generated_at(millis: Any) -> str | None:
    try:
        value = int(millis)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    if value > 10_000_000_000:
        value = value / 1000
    return datetime.fromtimestamp(value, tz=UTC).isoformat()


def _detail_dir(meta: dict, repo: str) -> str:
    detail_url = str(meta.get("detailUrl") or "").strip()
    if detail_url:
        if detail_url.endswith("/"):
            return detail_url.rstrip("/")
        return detail_url.rsplit("/", 1)[0]
    return f"/service/rest/healthcheck/healthCheckDetail/{repo}/current"


def _candidate_repos(eco: EcosystemConfig) -> list[str]:
    out: list[str] = []
    for name in (eco.health_repo, eco.proxy_repo):
        if name and name not in out:
            out.append(name)
    return out


async def _get_json(
    client: httpx.AsyncClient, url: str, *, timeout: float
) -> tuple[int, Any]:
    response = await client.get(
        url, auth=_auth(), timeout=timeout, follow_redirects=True
    )
    if response.status_code == 404:
        return 404, None
    response.raise_for_status()
    return response.status_code, response.json()


async def _fetch_repo_health(
    client: httpx.AsyncClient, ecosystem: str, repo: str
) -> ProxyHealthResponse | None:
    base = settings.nexus_base_url.rstrip("/")
    status, meta = await _get_json(client, f"{base}{META_PATH.format(repo=repo)}", timeout=30.0)
    if status == 404 or not isinstance(meta, dict):
        return None

    detail_dir = _detail_dir(meta, repo)
    sec_status, security_payload = await _get_json(
        client, f"{base}{detail_dir}/{DETAIL_JSON['security']}", timeout=60.0
    )
    lic_status, license_payload = await _get_json(
        client, f"{base}{detail_dir}/{DETAIL_JSON['licenses']}", timeout=60.0
    )
    if sec_status == 404 and lic_status == 404:
        return None

    vulnerabilities = [
        item
        for raw in _aa_data(security_payload)
        if (item := map_vulnerability(raw)) is not None
    ]
    licenses = [
        item
        for raw in _aa_data(license_payload)
        if (item := map_license(raw)) is not None
    ]
    result = ProxyHealthResponse(
        ecosystem=ecosystem,
        repository=str(meta.get("repositoryName") or repo),
        generated_at=_generated_at(meta.get("lastAnalyzedDate")),
        vulnerabilities=vulnerabilities,
        licenses=licenses,
    )
    eco = ECOSYSTEM_MAP[ecosystem]
    await _attach_import_status(client, eco, result)
    return result


async def _attach_import_status(
    client: httpx.AsyncClient,
    eco: EcosystemConfig,
    result: ProxyHealthResponse,
) -> None:
    keys: set[tuple[str, str]] = set()
    for item in (*result.vulnerabilities, *result.licenses):
        if item.artifact and item.version:
            keys.add((item.artifact, item.version))
    dates, hosted_keys = await blob_created_map(
        client,
        hosted_repo=eco.hosted_repo,
        health_repo=eco.health_repo,
        package_format=eco.ecosystem,
        keys=keys,
    )
    fmt = eco.ecosystem
    for item in (*result.vulnerabilities, *result.licenses):
        name_key = import_name_key(item.artifact, fmt)
        pair = (name_key, item.version)
        item.imported_at = dates.get(pair)
        item.in_hosted = pair in hosted_keys


async def fetch_proxy_health(ecosystem: str) -> ProxyHealthResponse:
    key = ecosystem.lower().strip()
    if key not in ECOSYSTEM_MAP:
        raise ValueError(f"Unsupported package type: {ecosystem}")
    eco = ECOSYSTEM_MAP[key]
    last_http_error: httpx.HTTPError | None = None
    async with httpx.AsyncClient(verify=settings.nexus_verify_ssl) as client:
        for repo in _candidate_repos(eco):
            try:
                result = await _fetch_repo_health(client, key, repo)
            except httpx.HTTPError as exc:
                last_http_error = exc
                continue
            if result is not None:
                return result
    if last_http_error is not None:
        raise last_http_error
    raise ProxyHealthUnavailable(
        f"Nexus health report not found for {eco.health_repo} or {eco.proxy_repo}"
    )
