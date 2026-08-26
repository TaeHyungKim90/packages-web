from __future__ import annotations

from typing import Any

from app.services import github
from app.services.ghes_models import (
    InventoryOrg,
    InventoryRepo,
    StoredOrg,
    StoredRepo,
)
from app.services.store_orgs import (
    get_synced_at,
    load_inventory,
    load_orgs,
    save_orgs,
)

__all__ = [
    "InventoryOrg",
    "InventoryRepo",
    "StoredOrg",
    "StoredRepo",
    "load_yaml",
    "save_yaml",
    "merge_with_yaml",
    "build_inventory",
    "sync_inventory",
    "list_cached_inventory",
    "inventory_to_stored",
    "_parse_org",
]


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


def load_yaml(path=None) -> list[StoredOrg]:
    del path
    return load_orgs()


def save_yaml(orgs: list[StoredOrg] | list[InventoryOrg], path=None) -> None:
    del path
    save_orgs(orgs)


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
    """Live GHES + DB managed merge (used by sync)."""
    live = await fetch_live_inventory()
    stored = load_yaml()
    return merge_with_yaml(live, stored)


def list_cached_inventory() -> tuple[list[InventoryOrg], str | None]:
    """DB-only view for GET."""
    return load_inventory(), get_synced_at()


async def sync_inventory() -> tuple[list[InventoryOrg], str | None]:
    """Fetch GHES, merge managed flags, persist to DB."""
    orgs = await build_inventory()
    save_orgs(orgs, touch_synced_at=True)
    return orgs, get_synced_at()


def inventory_to_stored(orgs: list[InventoryOrg]) -> list[StoredOrg]:
    return [
        StoredOrg(
            name=o.name,
            managed=o.managed,
            present=o.present,
            repos=[
                StoredRepo(name=r.name, managed=r.managed, present=r.present)
                for r in o.repos
            ],
        )
        for o in orgs
    ]
