from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException, Path

from app.db import connect
from app.deps import require_user
from app.nexus_http import nexus_http_exception
from app.schemas import (
    ProxyHealthResponse,
    ProxyHealthVulnOverride,
    ProxyHealthVulnOverrideKey,
    ProxyHealthVulnOverrideUpdate,
)
from app.services.nexus_health import ProxyHealthUnavailable
from app.services.osv import is_package_fixed_version
from app.services.proxy_health_store import (
    delete_vuln_override,
    get_proxy_health_cached,
    save_vuln_override,
)
from app.services.session import SessionUser

router = APIRouter(prefix="/proxy-health", tags=["proxy-health"])

CurrentUser = Annotated[SessionUser, Depends(require_user)]
SUPPORTED = frozenset({"pypi", "npm", "nuget"})
EcoPath = Annotated[str, Path(description="Package ecosystem: pypi | npm | nuget")]


def _require_eco(eco: str) -> str:
    key = eco.lower().strip()
    if key not in SUPPORTED:
        allowed = ", ".join(sorted(SUPPORTED))
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported ecosystem: {eco}. Use one of: {allowed}",
        )
    return key


def _validate_fixed_version(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    if not is_package_fixed_version(text):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid fixed version: {text}",
        )
    return text


@router.get("/{eco}", response_model=ProxyHealthResponse)
async def get_proxy_health(_user: CurrentUser, eco: EcoPath):
    key = _require_eco(eco)
    try:
        return await get_proxy_health_cached(key)
    except ProxyHealthUnavailable as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except httpx.HTTPStatusError as exc:
        raise nexus_http_exception(exc) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to reach Nexus: {exc}",
        ) from exc


@router.put("/{eco}/overrides", response_model=ProxyHealthVulnOverride)
async def put_vuln_override(
    _user: CurrentUser, eco: EcoPath, body: ProxyHealthVulnOverrideUpdate
):
    key = _require_eco(eco)
    problem_code = body.problem_code.strip()
    artifact = body.artifact.strip()
    if not problem_code or not artifact:
        raise HTTPException(
            status_code=400, detail="problem_code and artifact are required"
        )
    _validate_fixed_version(body.fixed_version)
    conn = connect()
    try:
        try:
            saved = save_vuln_override(conn, key, body)
            conn.commit()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        conn.close()
    return saved


@router.delete("/{eco}/overrides")
async def delete_vuln_override_route(
    _user: CurrentUser, eco: EcoPath, body: ProxyHealthVulnOverrideKey
):
    key = _require_eco(eco)
    problem_code = body.problem_code.strip()
    artifact = body.artifact.strip()
    if not problem_code or not artifact:
        raise HTTPException(
            status_code=400, detail="problem_code and artifact are required"
        )
    conn = connect()
    try:
        deleted = delete_vuln_override(conn, key, problem_code, artifact)
        conn.commit()
    finally:
        conn.close()
    if not deleted:
        raise HTTPException(status_code=404, detail="Override not found")
    return {"ok": True}
