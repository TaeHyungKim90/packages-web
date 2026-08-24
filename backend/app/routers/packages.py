from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query

from app.deps import require_user
from app.nexus_http import nexus_http_exception
from app.schemas import PackageCheckResponse, PackageListResponse
from app.services import nexus
from app.services.session import SessionUser

router = APIRouter(tags=["packages"])

VALID_FORMATS = {"pypi", "npm", "nuget"}
CurrentUser = Annotated[SessionUser, Depends(require_user)]


def _validate_format(fmt: str, raw_format: str) -> None:
    if fmt and fmt not in VALID_FORMATS:
        allowed = ", ".join(sorted(VALID_FORMATS))
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported format: {raw_format}. Use one of: {allowed}",
        )


@router.get("/packages/check", response_model=PackageCheckResponse)
async def check_package(
    _user: CurrentUser,
    format: str = Query(description="Package format: pypi | npm | nuget"),
    name: str = Query(description="Package name keyword (partial match)"),
    version: str = Query(default="", description="Optional version keyword (partial match)"),
    continuation_token: str | None = Query(default=None, alias="continuationToken"),
):
    fmt = format.lower().strip()
    _validate_format(fmt, format)

    pkg_name = name.strip()
    if not pkg_name:
        raise HTTPException(status_code=400, detail="name is required")

    repo = nexus.default_hosted_for_format(fmt)
    if not repo:
        raise HTTPException(status_code=400, detail=f"Unsupported format: {format}")

    try:
        return await nexus.check_package(
            repository=repo,
            package_format=fmt,
            name=pkg_name,
            version=version.strip(),
            continuation_token=continuation_token,
        )
    except httpx.HTTPStatusError as exc:
        raise nexus_http_exception(exc) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to reach Nexus: {exc}",
        ) from exc


@router.get("/packages", response_model=PackageListResponse)
async def list_packages(
    _user: CurrentUser,
    repository: str = Query(default="", description="Nexus hosted repository name"),
    format: str = Query(default="", description="Package format: pypi | npm | nuget"),
    q: str = Query(default="", description="Keyword search"),
    continuation_token: str | None = Query(default=None, alias="continuationToken"),
):
    fmt = format.lower().strip()
    _validate_format(fmt, format)

    repo = repository.strip()
    if not repo and fmt:
        repo = nexus.default_hosted_for_format(fmt)
    if not repo:
        raise HTTPException(
            status_code=400,
            detail="repository is required (or provide a supported format)",
        )

    try:
        return await nexus.search_packages(
            repository=repo,
            format=fmt,
            q=q.strip(),
            continuation_token=continuation_token,
        )
    except httpx.HTTPStatusError as exc:
        raise nexus_http_exception(exc) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to reach Nexus: {exc}",
        ) from exc
