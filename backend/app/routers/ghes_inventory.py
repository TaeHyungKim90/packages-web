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


def _to_response(orgs: list[ghes_inventory.InventoryOrg]) -> GhesOrgsResponse:
    return GhesOrgsResponse(
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
        ]
    )


@router.get("", response_model=GhesOrgsResponse)
async def get_ghes_orgs(_user: CurrentUser) -> GhesOrgsResponse:
    try:
        orgs = await ghes_inventory.build_inventory()
    except GitHubError as exc:
        status = exc.status_code or 502
        if status == 503:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return _to_response(orgs)


@router.put("", response_model=GhesOrgsResponse)
async def save_ghes_orgs(
    _user: CurrentUser,
    body: GhesOrgsSaveBody,
) -> GhesOrgsResponse:
    stored = [
        ghes_inventory.StoredOrg(
            name=o.name.strip(),
            managed=o.managed,
            repos=[
                ghes_inventory.StoredRepo(name=r.name.strip(), managed=r.managed)
                for r in o.repos
                if r.name.strip()
            ],
        )
        for o in body.organizations
        if o.name.strip()
    ]
    try:
        ghes_inventory.save_yaml(stored)
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to write ghes-orgs.yaml: {exc}",
        ) from exc

    # Return merged view again so UI stays consistent with GHES
    try:
        orgs = await ghes_inventory.build_inventory()
    except GitHubError as exc:
        # Save succeeded; return saved snapshot if live fetch fails
        return GhesOrgsResponse(
            organizations=[
                GhesOrgItem(
                    name=o.name,
                    managed=o.managed,
                    present=True,
                    repos=[
                        GhesRepoItem(name=r.name, managed=r.managed, present=True)
                        for r in o.repos
                    ],
                )
                for o in stored
            ]
        )
    return _to_response(orgs)
