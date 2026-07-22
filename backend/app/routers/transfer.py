from fastapi import APIRouter, HTTPException

from app.schemas import TransferRequest, TransferResult

router = APIRouter(tags=["transfer"])


@router.post("/transfer", response_model=TransferResult, status_code=202)
async def transfer_package(body: TransferRequest):
    """GitOps 이관 요청 (3단계에서 구현)."""
    raise HTTPException(status_code=501, detail="Not implemented yet (phase 3)")


@router.get("/transfer/{ecosystem}/{pr_number}", response_model=TransferResult)
async def get_transfer_status(ecosystem: str, pr_number: int):
    """PR/CI 상태 조회 (3단계에서 구현)."""
    raise HTTPException(status_code=501, detail="Not implemented yet (phase 3)")
