from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class StoredRepo:
    name: str
    managed: bool = False
    present: bool = True


@dataclass
class StoredOrg:
    name: str
    managed: bool = False
    present: bool = True
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
