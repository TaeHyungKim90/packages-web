from __future__ import annotations

import re
from datetime import UTC, datetime

import yaml

from app.config import EcosystemConfig, settings
from app.services import github, nexus
from app.services.github import PullRequest


class RequestRejected(Exception):
    """Business-rule rejection (duplicate, validation)."""


def _slug(name: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "-", name).strip("-").lower()
    return cleaned[:40] or "pkg"


def _parse_packages_doc(raw: str | None, ecosystem: str) -> dict:
    if not raw or not raw.strip():
        return {"ecosystem": ecosystem, "packages": []}
    data = yaml.safe_load(raw) or {}
    if not isinstance(data, dict):
        return {"ecosystem": ecosystem, "packages": []}
    packages = data.get("packages") or []
    if not isinstance(packages, list):
        packages = []
    data["ecosystem"] = data.get("ecosystem") or ecosystem
    data["packages"] = packages
    return data


def _inventory_has(raw: str | None, name: str, version: str) -> bool:
    if not raw:
        return False
    data = yaml.safe_load(raw) or {}
    packages = data.get("packages") if isinstance(data, dict) else None
    if not isinstance(packages, list):
        if isinstance(data, list):
            packages = data
        else:
            return False

    name_l = name.lower()
    for item in packages:
        if isinstance(item, str):
            # Prefer name@version; use rpartition so scoped npm (@scope/pkg@1.0.0) works.
            if "@" in item:
                n, sep, v = item.rpartition("@")
                if sep and n and v and n.lower() == name_l and v == version:
                    return True
            continue
        if not isinstance(item, dict):
            continue
        item_name = str(item.get("name", "")).lower()
        if item_name != name_l:
            continue
        versions = item.get("versions")
        if isinstance(versions, list) and version in [str(v) for v in versions]:
            return True
        if str(item.get("version", "")) == version:
            return True
    return False


def merge_request_package(doc: dict, *, name: str, version: str) -> dict:
    packages: list = list(doc.get("packages") or [])
    name_l = name.lower()
    for pkg in packages:
        if not isinstance(pkg, dict):
            continue
        if str(pkg.get("name", "")).lower() != name_l:
            continue
        versions = [str(v) for v in (pkg.get("versions") or [])]
        if version in versions:
            raise RequestRejected(f"{name}=={version} already in requests list")
        versions.append(version)
        pkg["versions"] = versions
        pkg["name"] = pkg.get("name") or name
        return {**doc, "packages": packages}

    packages.append({"name": name, "versions": [version]})
    return {**doc, "packages": packages}


def dump_requests_yaml(doc: dict) -> str:
    return yaml.safe_dump(doc, sort_keys=False, allow_unicode=True)


async def hosted_has_exact(eco: EcosystemConfig, name: str, version: str) -> bool:
    result = await nexus.check_package(
        repository=eco.hosted_repo,
        package_format=eco.ecosystem,
        name=name,
        version="",
    )
    name_l = name.lower()
    for pkg in result.packages:
        if pkg.name.lower() == name_l and version in pkg.versions:
            return True
    return False


async def _hosted_has_exact(eco: EcosystemConfig, name: str, version: str) -> bool:
    return await hosted_has_exact(eco, name, version)

def _requests_has(doc: dict, name: str, version: str) -> bool:
    name_l = name.lower()
    for pkg in doc.get("packages") or []:
        if not isinstance(pkg, dict):
            continue
        if str(pkg.get("name", "")).lower() != name_l:
            continue
        versions = [str(v) for v in (pkg.get("versions") or [])]
        if version in versions:
            return True
    return False


async def validate_package_request(
    *,
    eco: EcosystemConfig,
    name: str,
    version: str,
) -> list[dict[str, str | bool]]:
    """Return validation checks. Each: key, label, passed, detail."""
    owner = settings.github_org
    repo = eco.gitops_repo
    base = settings.github_base_branch
    checks: list[dict[str, str | bool]] = []

    try:
        upstream_ok = await nexus.upstream_version_exists(
            package_format=eco.ecosystem,
            proxy_repo=eco.proxy_repo,
            name=name,
            version=version,
        )
        source = "PyPI" if eco.ecosystem == "pypi" else eco.ecosystem
        checks.append(
            {
                "key": "upstream",
                "label": "업스트림 버전 존재",
                "passed": upstream_ok,
                "detail": (
                    f"{source}에 {name}=={version} 확인됨."
                    if upstream_ok
                    else f"{source}에 {name}=={version}이(가) 없습니다."
                ),
            }
        )
    except Exception as exc:  # noqa: BLE001 — surface as failed check
        checks.append(
            {
                "key": "upstream",
                "label": "업스트림 버전 존재",
                "passed": False,
                "detail": f"업스트림 확인 실패: {exc}",
            }
        )

    in_hosted = await _hosted_has_exact(eco, name, version)
    checks.append(
        {
            "key": "hosted",
            "label": "Hosted에 이미 등록됨",
            "passed": not in_hosted,
            "detail": (
                f"{eco.hosted_repo}에 등록되어 신청할 수 없습니다."
                if in_hosted
                else f"{eco.hosted_repo}에 없음"
            ),
        }
    )

    inv_file = await github.get_file(owner, repo, eco.inventory_file, ref=base)
    in_inventory = bool(inv_file and _inventory_has(inv_file.content, name, version))
    checks.append(
        {
            "key": "inventory",
            "label": "Inventory에 이미 등록됨",
            "passed": not in_inventory,
            "detail": (
                "inventory에 등록되어 신청할 수 없습니다."
                if in_inventory
                else "inventory에 없음"
            ),
        }
    )

    req_file = await github.get_file(owner, repo, eco.requests_file, ref=base)
    doc = _parse_packages_doc(req_file.content if req_file else None, eco.ecosystem)
    in_requests = _requests_has(doc, name, version)
    checks.append(
        {
            "key": "requests",
            "label": "요청 목록 중복 없음",
            "passed": not in_requests,
            "detail": (
                "requests YAML에 이미 있습니다."
                if in_requests
                else "요청 목록에 없습니다."
            ),
        }
    )

    return checks


async def submit_package_request(
    *,
    eco: EcosystemConfig,
    packages: list[tuple[str, str]],
    requested_by: str,
) -> tuple[PullRequest, str, bool, str]:
    """Create GitOps PR. Returns (pr, branch, automerge_ok, automerge_detail)."""
    if not packages:
        raise RequestRejected("at least one package is required")

    owner = settings.github_org
    repo = eco.gitops_repo
    base = settings.github_base_branch

    seen: set[tuple[str, str]] = set()
    for name, version in packages:
        key = (name.lower(), version)
        if key in seen:
            raise RequestRejected(f"duplicate in request: {name}=={version}")
        seen.add(key)
        checks = await validate_package_request(eco=eco, name=name, version=version)
        failed = [c for c in checks if not c["passed"]]
        if failed:
            raise RequestRejected(f"{name}=={version}: {failed[0]['detail']}")

    req_file = await github.get_file(owner, repo, eco.requests_file, ref=base)
    doc = _parse_packages_doc(req_file.content if req_file else None, eco.ecosystem)
    for name, version in packages:
        doc = merge_request_package(doc, name=name, version=version)
    new_yaml = dump_requests_yaml(doc)

    date = datetime.now(UTC).strftime("%Y%m%d")
    first_name = packages[0][0]
    branch = f"request/{date}-web-{_slug(first_name)}"
    if len(packages) > 1:
        branch = f"{branch}-x{len(packages)}"
    base_sha = await github.get_ref_sha(owner, repo, f"heads/{base}")
    await github.create_branch(owner, repo, branch=branch, from_sha=base_sha)

    branch_file = await github.get_file(owner, repo, eco.requests_file, ref=branch)
    labels = ", ".join(f"{n}=={v}" for n, v in packages)
    await github.put_file(
        owner,
        repo,
        path=eco.requests_file,
        content=new_yaml,
        message=f"request: add {labels} via packages-web",
        branch=branch,
        sha=branch_file.sha if branch_file else None,
    )

    pkg_lines = "\n".join(f"- `{n}=={v}`" for n, v in packages)
    body = (
        f"## Package request (packages-web)\n\n"
        f"- Ecosystem: `{eco.ecosystem}`\n"
        f"- Packages:\n{pkg_lines}\n"
        f"- Requested-by: @{requested_by}\n"
    )
    title = (
        f"request: {packages[0][0]}=={packages[0][1]}"
        if len(packages) == 1
        else f"request: {len(packages)} packages ({packages[0][0]}=={packages[0][1]}, …)"
    )
    pr = await github.create_pull(
        owner,
        repo,
        title=title,
        body=body,
        head=branch,
        base=base,
    )

    automerge_ok = False
    automerge_detail = ""
    if settings.transfer_auto_merge and pr.node_id:
        # Native auto-merge — merges only after required checks pass.
        automerge_ok, automerge_detail = await github.enable_automerge(pr.node_id)
        if automerge_ok:
            # If checks are already green, GitHub may not merge until refresh —
            # try an immediate merge when the PR is ready.
            pr = await github.merge_if_ready(owner, repo, pr.number)
        else:
            # Still try merge-if-ready (e.g. repo has no auto-merge feature but
            # checks are already clean). Does not force-merge blocked PRs.
            pr = await github.merge_if_ready(owner, repo, pr.number)

    return pr, branch, automerge_ok, automerge_detail
