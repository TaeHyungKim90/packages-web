from __future__ import annotations

import json
import tomllib
from typing import Any


def parse_uv_lock(text: str) -> list[tuple[str, str]]:
    data = tomllib.loads(text)
    found: set[tuple[str, str]] = set()
    for item in data.get("package") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        version = str(item.get("version") or "").strip()
        if name and version:
            found.add((name, version))
    return sorted(found)


def _npm_name_from_key(key: str) -> str | None:
    key = key.strip()
    if not key or key == "":
        return None
    marker = "node_modules/"
    if marker not in key:
        return None
    name = key.rsplit(marker, 1)[-1].strip()
    return name or None


def parse_package_lock(text: str) -> list[tuple[str, str]]:
    data = json.loads(text)
    packages = data.get("packages")
    found: set[tuple[str, str]] = set()
    if isinstance(packages, dict):
        for key, meta in packages.items():
            if not isinstance(meta, dict):
                continue
            name = _npm_name_from_key(str(key))
            if not name:
                continue
            version = str(meta.get("version") or "").strip()
            if version:
                found.add((name, version))
        return sorted(found)

    deps = data.get("dependencies")
    if isinstance(deps, dict):
        _walk_npm_legacy(deps, found)
    return sorted(found)


def _walk_npm_legacy(deps: dict[str, Any], found: set[tuple[str, str]]) -> None:
    for name, meta in deps.items():
        if not isinstance(meta, dict):
            continue
        version = str(meta.get("version") or "").strip()
        pkg = str(name).strip()
        if pkg and version:
            found.add((pkg, version))
        nested = meta.get("dependencies")
        if isinstance(nested, dict):
            _walk_npm_legacy(nested, found)


def parse_nuget_lock(text: str) -> list[tuple[str, str]]:
    data = json.loads(text)
    found: set[tuple[str, str]] = set()
    dependencies = data.get("dependencies")
    if not isinstance(dependencies, dict):
        return []
    for _tfm, packages in dependencies.items():
        if not isinstance(packages, dict):
            continue
        for pkg_id, meta in packages.items():
            if not isinstance(meta, dict):
                continue
            kind = str(meta.get("type") or "").lower()
            if kind == "project":
                continue
            name = str(pkg_id).strip()
            version = str(meta.get("resolved") or "").strip()
            if name and version:
                found.add((name, version))
    return sorted(found)


def parse_lock(format: str, text: str) -> list[tuple[str, str]]:
    if format == "pypi":
        return parse_uv_lock(text)
    if format == "npm":
        return parse_package_lock(text)
    if format == "nuget":
        return parse_nuget_lock(text)
    raise ValueError(f"Unsupported lock format: {format}")
