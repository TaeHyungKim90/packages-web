from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.deps import require_sk_inc
from app.schemas import (
    GhesOrgItem,
    GhesOrgsResponse,
    GhesOrgsSaveBody,
    GhesRepoItem,
)
from app.services import ghes_inventory
from app.services.github import GitHubError
from app.services.session import SessionUser

router = APIRouter(prefix="/ghes-orgs", tags=["ghes-orgs"])

CurrentUser = Annotated[SessionUser, Depends(require_sk_inc)]


def _to_response(
    orgs: list[ghes_inventory.InventoryOrg],
    *,
    synced_at: str | None = None,
) -> GhesOrgsResponse:
    return GhesOrgsResponse(
        synced_at=synced_at,
        organizations=[
            GhesOrgItem(
                name=o.name,
                managed=o.managed,
                present=o.present,
                repos=[
                    GhesRepoItem(
                        name=r.name,
                        managed=r.managed,
                        present=r.present,
                    )
                    for r in o.repos
                ],
            )
            for o in orgs
        ],
    )


@router.get("", response_model=GhesOrgsResponse)
async def get_ghes_orgs(_user: CurrentUser) -> GhesOrgsResponse:
    orgs, synced_at = ghes_inventory.list_cached_inventory()
    return _to_response(orgs, synced_at=synced_at)


@router.post("/sync", response_model=GhesOrgsResponse)
async def sync_ghes_orgs(_user: CurrentUser) -> GhesOrgsResponse:
    try:
        orgs, synced_at = await ghes_inventory.sync_inventory()
    except GitHubError as exc:
        status = exc.status_code or 502
        if status == 503:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return _to_response(orgs, synced_at=synced_at)


@router.put("", response_model=GhesOrgsResponse)
async def save_ghes_orgs(
    _user: CurrentUser,
    body: GhesOrgsSaveBody,
) -> GhesOrgsResponse:
    stored = [
        ghes_inventory.StoredOrg(
            name=o.name.strip(),
            managed=o.managed,
            present=True,
            repos=[
                ghes_inventory.StoredRepo(
                    name=r.name.strip(),
                    managed=r.managed,
                    present=True,
                )
                for r in o.repos
                if r.name.strip()
            ],
        )
        for o in body.organizations
        if o.name.strip()
    ]
    # Preserve present flags from existing cache when names match
    existing = {o.name: o for o in ghes_inventory.load_yaml()}
    for org in stored:
        prev = existing.get(org.name)
        if prev is None:
            continue
        org.present = prev.present
        prev_repos = {r.name: r for r in prev.repos}
        for repo in org.repos:
            pr = prev_repos.get(repo.name)
            if pr is not None:
                repo.present = pr.present
    try:
        ghes_inventory.save_yaml(stored)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to save GHES org inventory: {exc}",
        ) from exc

    orgs, synced_at = ghes_inventory.list_cached_inventory()
    return _to_response(orgs, synced_at=synced_at)
