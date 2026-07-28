from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from app.config import settings
from app.deps import require_user
from app.schemas import (
    PackageRequestBody,
    PackageRequestCheck,
    PackageRequestDeliveryItem,
    PackageRequestItem,
    PackageRequestItemValidation,
    PackageRequestResult,
    PackageRequestStatus,
    PackageRequestValidation,
)
from app.services import github, gitops
from app.services.github import GitHubError
from app.services.gitops import RequestRejected
from app.services.session import SessionUser

router = APIRouter(prefix="/request", tags=["request"])

CurrentUser = Annotated[SessionUser, Depends(require_user)]

SUPPORTED_REQUEST_ECOSYSTEMS = frozenset({"pypi", "npm", "nuget"})
EcoPath = Annotated[str, Path(description="Package ecosystem: pypi | npm | nuget")]


def _require_eco(eco: str) -> str:
    key = eco.lower().strip()
    if key not in SUPPORTED_REQUEST_ECOSYSTEMS:
        allowed = ", ".join(sorted(SUPPORTED_REQUEST_ECOSYSTEMS))
        raise HTTPException(
            status_code=404,
            detail=f"Unsupported ecosystem: {eco}. Use one of: {allowed}",
        )
    return key


def _normalize_packages(body: PackageRequestBody) -> list[tuple[str, str]]:
    if len(body.packages) > 10:
        raise HTTPException(status_code=400, detail="최대 10개까지 신청할 수 있습니다")
    out: list[tuple[str, str]] = []
    for item in body.packages:
        name = item.name.strip()
        version = item.version.strip()
        if not name or not version:
            raise HTTPException(status_code=400, detail="name and version are required")
        out.append((name, version))
    return out


def _parse_packages_query(packages: str | None) -> list[tuple[str, str]]:
    """Parse packages=name==ver,name2==ver2 (max 10). Supports scoped npm names."""
    if not packages or not packages.strip():
        return []
    out: list[tuple[str, str]] = []
    for part in packages.split(","):
        part = part.strip()
        if not part:
            continue
        if "==" not in part:
            raise HTTPException(
                status_code=400,
                detail="packages must be name==version[,name==version...]",
            )
        name, _, version = part.partition("==")
        name, version = name.strip(), version.strip()
        if not name or not version:
            raise HTTPException(status_code=400, detail="name and version are required")
        out.append((name, version))
        if len(out) > 10:
            raise HTTPException(status_code=400, detail="최대 10개까지 조회할 수 있습니다")
    return out


def _delivery_status(*, merged: bool, items: list[PackageRequestDeliveryItem]) -> str:
    if not merged:
        return "pending"
    if not items:
        return "merged"
    if all(i.in_hosted for i in items):
        return "done"
    return "delivering"


@router.post("/{eco}/validate", response_model=PackageRequestValidation)
async def validate_request(
    eco: EcoPath,
    body: PackageRequestBody,
    _user: CurrentUser,
) -> PackageRequestValidation:
    eco_key = _require_eco(eco)
    packages = _normalize_packages(body)

    if not settings.github_token:
        raise HTTPException(status_code=503, detail="GITHUB_TOKEN is not configured")

    eco_cfg = settings.get_ecosystem(eco_key)
    seen: set[tuple[str, str]] = set()
    items: list[PackageRequestItemValidation] = []

    for name, version in packages:
        key = (name.lower(), version)
        try:
            raw_checks = await gitops.validate_package_request(
                eco=eco_cfg, name=name, version=version
            )
        except GitHubError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        checks = [PackageRequestCheck(**c) for c in raw_checks]
        if key in seen:
            checks.append(
                PackageRequestCheck(
                    key="duplicate",
                    label="요청 내 중복 없음",
                    passed=False,
                    detail="같은 이름·버전이 요청에 중복됩니다.",
                )
            )
        else:
            checks.append(
                PackageRequestCheck(
                    key="duplicate",
                    label="요청 내 중복 없음",
                    passed=True,
                    detail="요청 내 중복 없음.",
                )
            )
        seen.add(key)
        items.append(
            PackageRequestItemValidation(
                name=name,
                version=version,
                can_request=all(c.passed for c in checks),
                checks=checks,
            )
        )

    return PackageRequestValidation(
        can_request=all(i.can_request for i in items),
        items=items,
    )


@router.post("/{eco}", response_model=PackageRequestResult)
async def submit_request(
    eco: EcoPath,
    body: PackageRequestBody,
    user: CurrentUser,
) -> PackageRequestResult:
    eco_key = _require_eco(eco)
    packages = _normalize_packages(body)

    if not settings.github_token:
        raise HTTPException(status_code=503, detail="GITHUB_TOKEN is not configured")

    eco_cfg = settings.get_ecosystem(eco_key)
    try:
        pr, branch, automerge, automerge_detail = await gitops.submit_package_request(
            eco=eco_cfg,
            packages=packages,
            requested_by=user.login,
        )
    except RequestRejected as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except GitHubError as exc:
        status = exc.status_code or 502
        if status == 503:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return PackageRequestResult(
        ecosystem=eco_key,
        packages=[PackageRequestItem(name=n, version=v) for n, v in packages],
        repository=f"{settings.github_org}/{eco_cfg.gitops_repo}",
        branch=branch,
        pr_number=pr.number,
        pr_url=pr.html_url,
        pr_state=pr.state,
        merged=pr.merged,
        automerge=automerge,
        automerge_detail=automerge_detail,
        requested_by=user.login,
    )


@router.get("/{eco}/{pr_number}", response_model=PackageRequestStatus)
async def request_status(
    eco: EcoPath,
    pr_number: int,
    _user: CurrentUser,
    packages: Annotated[str | None, Query()] = None,
) -> PackageRequestStatus:
    eco_key = _require_eco(eco)
    if not settings.github_token:
        raise HTTPException(status_code=503, detail="GITHUB_TOKEN is not configured")

    pkg_list = _parse_packages_query(packages)
    eco_cfg = settings.get_ecosystem(eco_key)
    try:
        # If CI is already green, attempt merge (does not force-merge blocked PRs).
        pr = await github.merge_if_ready(settings.github_org, eco_cfg.gitops_repo, pr_number)
        raw = await github.get_pull_raw(settings.github_org, eco_cfg.gitops_repo, pr_number)
    except GitHubError as exc:
        status = exc.status_code or 502
        if status == 404:
            raise HTTPException(status_code=404, detail="PR not found") from exc
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    delivery_items: list[PackageRequestDeliveryItem] = []
    if pr.merged and pkg_list:
        for name, version in pkg_list:
            in_hosted = await gitops.hosted_has_exact(eco_cfg, name, version)
            delivery_items.append(
                PackageRequestDeliveryItem(
                    name=name, version=version, in_hosted=in_hosted
                )
            )
    elif pkg_list:
        delivery_items = [
            PackageRequestDeliveryItem(name=n, version=v, in_hosted=False)
            for n, v in pkg_list
        ]

    return PackageRequestStatus(
        ecosystem=eco_key,
        pr_number=pr.number,
        pr_url=pr.html_url,
        pr_state=pr.state,
        merged=pr.merged,
        title=pr.title,
        mergeable_state=str(raw.get("mergeable_state") or ""),
        packages=delivery_items,
        delivery=_delivery_status(merged=pr.merged, items=delivery_items),
    )
