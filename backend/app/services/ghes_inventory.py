from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from app.config import settings
from app.services import github


@dataclass
class StoredRepo:
    name: str
    managed: bool = False


@dataclass
class StoredOrg:
    name: str
    managed: bool = False
    repos: list[StoredRepo] = field(default_factory=list)


@dataclass
class InventoryRepo:
    name: str
    managed: bool = False
    present: bool = True


@dataclass
class InventoryOrg:
    name: str
    managed: bool = False
    present: bool = True
    repos: list[InventoryRepo] = field(default_factory=list)


def resolve_yaml_path() -> Path:
    configured = (settings.ghes_orgs_yaml_path or "").strip()
    if configured:
        return Path(configured)
    # backend/app/services -> repo root
    repo_root = Path(__file__).resolve().parents[3]
    return repo_root / "config" / "ghes-orgs.yaml"


def _parse_repo(raw: Any) -> StoredRepo | None:
    if isinstance(raw, str):
        name = raw.strip()
        return StoredRepo(name=name, managed=False) if name else None
    if isinstance(raw, dict):
        name = str(raw.get("name") or "").strip()
        if not name:
            return None
        return StoredRepo(name=name, managed=bool(raw.get("managed", False)))
    return None


def _parse_org(raw: Any) -> StoredOrg | None:
    if not isinstance(raw, dict):
        return None
    name = str(raw.get("name") or "").strip()
    if not name:
        return None
    repos: list[StoredRepo] = []
    for item in raw.get("repos") or []:
        repo = _parse_repo(item)
        if repo is not None:
            repos.append(repo)
    return StoredOrg(
        name=name,
        managed=bool(raw.get("managed", False)),
        repos=repos,
    )


def load_yaml(path: Path | None = None) -> list[StoredOrg]:
    target = path or resolve_yaml_path()
    if not target.is_file():
        return []
    raw = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        return []
    orgs: list[StoredOrg] = []
    for item in raw.get("organizations") or []:
        org = _parse_org(item)
        if org is not None:
            orgs.append(org)
    return orgs


def save_yaml(orgs: list[StoredOrg] | list[InventoryOrg], path: Path | None = None) -> None:
    target = path or resolve_yaml_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "organizations": [
            {
                "name": org.name,
                "managed": bool(org.managed),
                "repos": [
                    {"name": repo.name, "managed": bool(repo.managed)}
                    for repo in org.repos
                ],
            }
            for org in orgs
        ]
    }
    header = (
        "# GHES 조직 · 레포 인벤토리\n"
        "# managed: 관리 대상 여부 (UI에서 저장)\n"
        "# GET /api/ghes-orgs 는 GHES API와 이 파일을 병합합니다.\n"
        "\n"
    )
    body = yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)
    target.write_text(header + body, encoding="utf-8")


def merge_with_yaml(
    live: dict[str, list[str]],
    stored: list[StoredOrg],
) -> list[InventoryOrg]:
    stored_by_name = {o.name: o for o in stored}
    result: list[InventoryOrg] = []

    for org_name in sorted(live.keys(), key=str.lower):
        stored_org = stored_by_name.get(org_name)
        stored_repos = {r.name: r for r in (stored_org.repos if stored_org else [])}
        live_repos = live[org_name]
        repos: list[InventoryRepo] = []
        for repo_name in sorted(live_repos, key=str.lower):
            sr = stored_repos.get(repo_name)
            repos.append(
                InventoryRepo(
                    name=repo_name,
                    managed=bool(sr.managed) if sr else False,
                    present=True,
                )
            )
        for repo_name, sr in sorted(stored_repos.items(), key=lambda x: x[0].lower()):
            if repo_name not in live_repos:
                repos.append(
                    InventoryRepo(
                        name=repo_name,
                        managed=bool(sr.managed),
                        present=False,
                    )
                )
        result.append(
            InventoryOrg(
                name=org_name,
                managed=bool(stored_org.managed) if stored_org else False,
                present=True,
                repos=repos,
            )
        )

    for org_name, stored_org in sorted(stored_by_name.items(), key=lambda x: x[0].lower()):
        if org_name in live:
            continue
        result.append(
            InventoryOrg(
                name=org_name,
                managed=bool(stored_org.managed),
                present=False,
                repos=[
                    InventoryRepo(
                        name=r.name,
                        managed=bool(r.managed),
                        present=False,
                    )
                    for r in stored_org.repos
                ],
            )
        )
    return result


async def fetch_live_inventory() -> dict[str, list[str]]:
    orgs = await github.list_all_organizations()
    live: dict[str, list[str]] = {}
    for org in orgs:
        live[org] = await github.list_org_repos(org)
    return live


async def build_inventory() -> list[InventoryOrg]:
    live = await fetch_live_inventory()
    stored = load_yaml()
    return merge_with_yaml(live, stored)


def inventory_to_stored(orgs: list[InventoryOrg]) -> list[StoredOrg]:
    return [
        StoredOrg(
            name=o.name,
            managed=o.managed,
            repos=[StoredRepo(name=r.name, managed=r.managed) for r in o.repos],
        )
        for o in orgs
    ]
