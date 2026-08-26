from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

from app.db import connect
from app.services.ghes_models import InventoryOrg, InventoryRepo, StoredOrg, StoredRepo


def load_orgs(conn: sqlite3.Connection | None = None) -> list[StoredOrg]:
    own = conn is None
    if own:
        conn = connect()
    assert conn is not None
    orgs: list[StoredOrg] = []
    for org_row in conn.execute(
        "SELECT name, managed, present FROM ghes_org ORDER BY name COLLATE NOCASE"
    ):
        repos = [
            StoredRepo(
                name=r["name"],
                managed=bool(r["managed"]),
                present=bool(r["present"]),
            )
            for r in conn.execute(
                "SELECT name, managed, present FROM ghes_repo WHERE org_name = ? "
                "ORDER BY name COLLATE NOCASE",
                (org_row["name"],),
            )
        ]
        orgs.append(
            StoredOrg(
                name=org_row["name"],
                managed=bool(org_row["managed"]),
                present=bool(org_row["present"]),
                repos=repos,
            )
        )
    if own:
        conn.close()
    return orgs


def load_inventory(conn: sqlite3.Connection | None = None) -> list[InventoryOrg]:
    return [
        InventoryOrg(
            name=o.name,
            managed=o.managed,
            present=o.present,
            repos=[
                InventoryRepo(name=r.name, managed=r.managed, present=r.present)
                for r in o.repos
            ],
        )
        for o in load_orgs(conn)
    ]


def get_synced_at(conn: sqlite3.Connection | None = None) -> str | None:
    own = conn is None
    if own:
        conn = connect()
    assert conn is not None
    row = conn.execute(
        "SELECT synced_at FROM ghes_inventory_meta WHERE id = 1"
    ).fetchone()
    if own:
        conn.close()
    return row["synced_at"] if row else None


def set_synced_at(conn: sqlite3.Connection, synced_at: str | None = None) -> None:
    stamp = synced_at or datetime.now(tz=UTC).isoformat()
    conn.execute(
        "INSERT INTO ghes_inventory_meta (id, synced_at) VALUES (1, ?) "
        "ON CONFLICT(id) DO UPDATE SET synced_at = excluded.synced_at",
        (stamp,),
    )


def save_orgs_to_conn(
    conn: sqlite3.Connection,
    orgs: list[StoredOrg] | list[InventoryOrg],
    *,
    touch_synced_at: bool = False,
) -> None:
    conn.execute("DELETE FROM ghes_repo")
    conn.execute("DELETE FROM ghes_org")
    for org in orgs:
        present = bool(getattr(org, "present", True))
        conn.execute(
            "INSERT INTO ghes_org (name, managed, present) VALUES (?, ?, ?)",
            (org.name, int(bool(org.managed)), int(present)),
        )
        for repo in org.repos:
            repo_present = bool(getattr(repo, "present", True))
            conn.execute(
                "INSERT INTO ghes_repo (org_name, name, managed, present) "
                "VALUES (?, ?, ?, ?)",
                (org.name, repo.name, int(bool(repo.managed)), int(repo_present)),
            )
    if touch_synced_at:
        set_synced_at(conn)


def save_orgs(
    orgs: list[StoredOrg] | list[InventoryOrg],
    *,
    touch_synced_at: bool = False,
) -> None:
    conn = connect()
    try:
        save_orgs_to_conn(conn, orgs, touch_synced_at=touch_synced_at)
        conn.commit()
    finally:
        conn.close()
