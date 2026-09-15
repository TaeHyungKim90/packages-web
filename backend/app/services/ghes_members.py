"""GHES 가입자·소속 조직 캐시 (관리 화면용)."""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import UTC, datetime

import httpx

from app.config import settings
from app.db import connect
from app.schemas import GhesMemberItem, GhesMembersResponse
from app.services.github import GitHubError, _api, _headers

logger = logging.getLogger(__name__)

SKIP_ORG = "sk-inc"
SKIP_USER_TYPES = frozenset({"organization", "bot"})
# GitHub Actions 시스템 계정 등
SKIP_LOGINS = frozenset({"actions-admin", "ghost"})


def _is_person_account(item: dict) -> bool:
    login = str(item.get("login") or "").strip().lower()
    if login in SKIP_LOGINS:
        return False
    user_type = str(item.get("type") or "User").strip().lower()
    return user_type not in SKIP_USER_TYPES


def _should_list_member(login: str, user_type: str) -> bool:
    if login.strip().lower() in SKIP_LOGINS:
        return False
    return user_type.strip().lower() not in SKIP_USER_TYPES



def _row_bool(value: object) -> bool:
    return bool(value) if value is not None else False


def _organizations_label(login: str, orgs: list[str]) -> str:
    admin = (settings.ghes_inventory_login or "sk-inc").strip().lower()
    if login.strip().lower() == admin:
        return "관리"
    return ",".join(orgs)


def list_cached_members() -> GhesMembersResponse:
    conn = connect()
    try:
        meta = conn.execute(
            "SELECT synced_at FROM ghes_member_meta WHERE id = 1"
        ).fetchone()
        synced_at = meta["synced_at"] if meta else None
        org_map: dict[str, list[str]] = defaultdict(list)
        for row in conn.execute(
            "SELECT login, org_name FROM ghes_member_org ORDER BY org_name COLLATE NOCASE"
        ):
            org_map[row["login"]].append(row["org_name"])
        members: list[GhesMemberItem] = []
        for row in conn.execute(
            "SELECT login, name, email, user_type, site_admin "
            "FROM ghes_member ORDER BY login COLLATE NOCASE"
        ):
            user_type = row["user_type"] or "User"
            login = row["login"]
            if not _should_list_member(login, user_type):
                continue
            orgs = org_map.get(login, [])
            members.append(
                GhesMemberItem(
                    login=login,
                    name=row["name"],
                    email=row["email"],
                    user_type=user_type,
                    site_admin=_row_bool(row["site_admin"]),
                    organizations=orgs,
                    organizations_label=_organizations_label(login, orgs),
                )
            )
        return GhesMembersResponse(synced_at=synced_at, members=members)
    finally:
        conn.close()


def _save_members(
    members: list[dict],
    membership: dict[str, list[str]],
    *,
    synced_at: str,
) -> None:
    conn = connect()
    try:
        conn.execute("DELETE FROM ghes_member_org")
        conn.execute("DELETE FROM ghes_member")
        for item in members:
            login = str(item.get("login") or "").strip()
            if not login or not _is_person_account(item):
                continue
            conn.execute(
                "INSERT INTO ghes_member "
                "(login, user_id, name, email, user_type, site_admin) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    login,
                    item.get("id"),
                    item.get("name"),
                    item.get("email"),
                    str(item.get("type") or "User"),
                    1 if item.get("site_admin") else 0,
                ),
            )
            for org in membership.get(login.lower(), []):
                if org.lower() == SKIP_ORG.lower():
                    continue
                conn.execute(
                    "INSERT OR IGNORE INTO ghes_member_org (login, org_name) VALUES (?, ?)",
                    (login, org),
                )
        conn.execute("DELETE FROM ghes_member_meta WHERE id = 1")
        conn.execute(
            "INSERT INTO ghes_member_meta (id, synced_at) VALUES (1, ?)",
            (synced_at,),
        )
        conn.commit()
    finally:
        conn.close()


async def _list_users(client: httpx.AsyncClient) -> list[dict]:
    users: list[dict] = []
    since = 0
    # GHES /users may return < per_page even when more users exist after `since`.
    # Stop only on an empty page (GitHub pagination by id).
    while True:
        response = await client.get(
            _api("/users"),
            params={"since": since, "per_page": 100},
            headers=_headers(),
            timeout=60.0,
        )
        if response.status_code >= 400:
            raise GitHubError(
                f"list users failed: {response.text[:300]}",
                status_code=response.status_code,
            )
        batch = response.json()
        if not isinstance(batch, list) or not batch:
            break
        for user in batch:
            if not isinstance(user, dict) or not user.get("login"):
                continue
            since = int(user.get("id") or since)
            # /users includes org/bot accounts — subscribers list is people only
            if not _is_person_account(user):
                continue
            users.append(user)
    return users


async def _enrich_user(client: httpx.AsyncClient, login: str) -> dict:
    response = await client.get(
        _api(f"/users/{login}"),
        headers=_headers(),
        timeout=60.0,
    )
    if response.status_code == 404:
        return {}
    if response.status_code >= 400:
        logger.warning("enrich user %s failed: HTTP %s", login, response.status_code)
        return {}
    data = response.json()
    return data if isinstance(data, dict) else {}


async def _list_orgs(client: httpx.AsyncClient) -> list[str]:
    orgs: list[str] = []
    since = 0
    # Empty page ends pagination (short pages can still have more after `since`).
    while True:
        response = await client.get(
            _api("/organizations"),
            params={"since": since, "per_page": 100},
            headers=_headers(),
            timeout=60.0,
        )
        if response.status_code >= 400:
            raise GitHubError(
                f"list orgs failed: {response.text[:300]}",
                status_code=response.status_code,
            )
        batch = response.json()
        if not isinstance(batch, list) or not batch:
            break
        for org in batch:
            if not isinstance(org, dict):
                continue
            login = str(org.get("login") or "").strip()
            oid = org.get("id")
            if oid is not None:
                since = int(oid)
            if not login or login.lower() == SKIP_ORG.lower():
                continue
            orgs.append(login)
    return orgs


async def _list_org_members(client: httpx.AsyncClient, org: str) -> list[str]:
    members: list[str] = []
    page = 1
    while True:
        response = await client.get(
            _api(f"/orgs/{org}/members"),
            params={"page": page, "per_page": 100},
            headers=_headers(),
            timeout=60.0,
        )
        if response.status_code in {403, 404}:
            logger.warning("skip members %s: HTTP %s", org, response.status_code)
            return []
        if response.status_code >= 400:
            raise GitHubError(
                f"members {org} failed: {response.text[:300]}",
                status_code=response.status_code,
            )
        batch = response.json()
        if not isinstance(batch, list) or not batch:
            break
        for user in batch:
            if not isinstance(user, dict):
                continue
            login = str(user.get("login") or "").strip()
            if login:
                members.append(login)
        if len(batch) < 100:
            break
        page += 1
    return members


async def sync_members() -> GhesMembersResponse:
    if not settings.github_token:
        raise GitHubError("GITHUB_TOKEN is not configured", status_code=503)

    async with httpx.AsyncClient(verify=False) as client:
        listed = await _list_users(client)
        members: list[dict] = []
        for item in listed:
            login = str(item.get("login") or "").strip()
            if not login:
                continue
            detail = await _enrich_user(client, login)
            merged = {**item, **detail}
            if not _is_person_account(merged):
                continue
            members.append(merged)

        orgs = await _list_orgs(client)
        membership: dict[str, list[str]] = defaultdict(list)
        for org in orgs:
            for login in await _list_org_members(client, org):
                membership[login.lower()].append(org)

    synced_at = datetime.now(tz=UTC).isoformat()
    _save_members(members, membership, synced_at=synced_at)
    return list_cached_members()
