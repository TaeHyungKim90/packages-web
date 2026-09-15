from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.deps import require_sk_inc
from app.schemas import GhesMembersResponse
from app.services import ghes_members
from app.services.github import GitHubError
from app.services.session import SessionUser

router = APIRouter(prefix="/ghes-members", tags=["ghes-members"])

CurrentUser = Annotated[SessionUser, Depends(require_sk_inc)]


@router.get("", response_model=GhesMembersResponse)
async def get_ghes_members(_user: CurrentUser) -> GhesMembersResponse:
    return ghes_members.list_cached_members()


@router.post("/sync", response_model=GhesMembersResponse)
async def sync_ghes_members(_user: CurrentUser) -> GhesMembersResponse:
    try:
        return await ghes_members.sync_members()
    except GitHubError as exc:
        status = exc.status_code or 502
        if status == 503:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        raise HTTPException(status_code=502, detail=str(exc)) from exc
