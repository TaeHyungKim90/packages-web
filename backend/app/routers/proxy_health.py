from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException, Path

from app.deps import require_user
from app.nexus_http import nexus_http_exception
from app.schemas import ProxyHealthResponse
from app.services.nexus_health import ProxyHealthUnavailable, fetch_proxy_health
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


@router.get("/{eco}", response_model=ProxyHealthResponse)
async def get_proxy_health(_user: CurrentUser, eco: EcoPath):
    key = _require_eco(eco)
    try:
        return await fetch_proxy_health(key)
    except ProxyHealthUnavailable as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except httpx.HTTPStatusError as exc:
        raise nexus_http_exception(exc) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to reach Nexus: {exc}",
        ) from exc
