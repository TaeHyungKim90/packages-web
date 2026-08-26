from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from app.deps import require_sk_inc
from app.schemas import (
    AggregatedPackageRow,
    ProjectPackagesListResponse,
    ProjectPackagesSyncResult,
)
from app.services import project_packages
from app.services.github import GitHubError
from app.services.session import SessionUser

router = APIRouter(prefix="/project-packages", tags=["project-packages"])

CurrentUser = Annotated[SessionUser, Depends(require_sk_inc)]


def _to_items(rows: list[project_packages.AggregatedRow]) -> list[AggregatedPackageRow]:
    return [
        AggregatedPackageRow(
            format=r.format,
            name=r.name,
            version=r.version,
            imported_at=r.imported_at,
            max_threat_level=r.max_threat_level,
            organizations=r.organizations,
        )
        for r in rows
    ]


@router.get("", response_model=ProjectPackagesListResponse)
async def list_project_packages(
    _user: CurrentUser,
    org: str | None = Query(default=None),
    name: str | None = Query(default=None),
    format: str | None = Query(default=None),
    refresh_imported: bool = Query(default=False),
    refresh_vulnerabilities: bool = Query(default=False),
) -> ProjectPackagesListResponse:
    snap = project_packages.load_snapshot_cached()
    rows = list(snap.aggregated)
    if refresh_imported or refresh_vulnerabilities:
        if refresh_imported:
            await project_packages.attach_imported_at(rows)
        if refresh_vulnerabilities:
            index = await project_packages.build_vulnerability_index()
            project_packages.attach_cve_scores(rows, index)
        snap.aggregated = rows
        project_packages._persist_snapshot(snap)
        snap = project_packages.load_snapshot_cached()
        rows = list(snap.aggregated)
    filtered = project_packages.filter_aggregated(
        rows, org=org, name=name, format=format
    )
    return ProjectPackagesListResponse(
        collected_at=snap.collected_at,
        items=_to_items(filtered),
    )


@router.post("/sync", response_model=ProjectPackagesSyncResult)
async def sync_project_packages(
    _user: CurrentUser,
    org: str | None = Query(default=None),
) -> ProjectPackagesSyncResult:
    try:
        snap = await project_packages.sync(org)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except GitHubError as exc:
        status = exc.status_code or 502
        if status == 503:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return ProjectPackagesSyncResult(
        collected_at=snap.collected_at,
        org_count=len(snap.projects),
        item_count=len(snap.aggregated),
        items=_to_items(snap.aggregated),
    )
