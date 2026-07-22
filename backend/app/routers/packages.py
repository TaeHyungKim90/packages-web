from fastapi import APIRouter, HTTPException

router = APIRouter(tags=["packages"])


@router.get("/packages")
async def list_packages(repository: str = "", format: str = ""):
    """Nexus Search API로 패키지 목록 조회 (2단계에서 구현)."""
    raise HTTPException(status_code=501, detail="Not implemented yet (phase 2)")
