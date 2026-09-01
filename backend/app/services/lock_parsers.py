from __future__ import annotations

import json
import tomllib
from pathlib import PurePosixPath
from typing import Any

import yaml


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


def _pnpm_key_to_name_version(key: str) -> tuple[str, str] | None:
    key = key.strip()
    if not key or key in {".", ""}:
        return None
    if "(" in key:
        key = key.split("(", 1)[0]
    if key.startswith("/"):
        key = key[1:]
    if "@" not in key:
        return None
    if key.startswith("@"):
        body = key[1:]
        if "@" not in body:
            return None
        name_body, version = body.rsplit("@", 1)
        name = f"@{name_body}"
    else:
        name, version = key.rsplit("@", 1)
    name = name.strip()
    version = version.strip()
    if not name or not version:
        return None
    if version.startswith(("link:", "file:", "workspace:")):
        return None
    return (name, version)


def parse_pnpm_lock(text: str) -> list[tuple[str, str]]:
    data = yaml.safe_load(text) or {}
    packages = data.get("packages")
    if not isinstance(packages, dict):
        return []
    found: set[tuple[str, str]] = set()
    for key in packages:
        parsed = _pnpm_key_to_name_version(str(key))
        if parsed:
            found.add(parsed)
    return sorted(found)


def _yarn_name_from_descriptor(desc: str) -> str | None:
    desc = desc.strip().strip('"').strip("'")
    if not desc or desc.startswith("__metadata"):
        return None
    # berry: "react@npm:^19.0.0" / classic: "react@^19.0.0"
    if desc.startswith("@"):
        body = desc[1:]
        if "@" not in body:
            return None
        name_body, _rest = body.split("@", 1)
        return f"@{name_body}"
    if "@" not in desc:
        return None
    return desc.split("@", 1)[0].strip() or None


def parse_yarn_lock(text: str) -> list[tuple[str, str]]:
    """Parse Yarn classic (v1) and Berry (v2+) lockfiles."""
    found: set[tuple[str, str]] = set()
    descriptors: list[str] = []
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if not raw.startswith((" ", "\t")) and raw.rstrip().endswith(":"):
            header = raw.rstrip()[:-1].strip()
            descriptors = [part.strip() for part in header.split(",")]
            continue
        stripped = raw.strip()
        version = ""
        if stripped.startswith("version "):
            version = stripped[len("version ") :].strip().strip('"').strip("'")
        elif stripped.startswith("version:"):
            version = stripped[len("version:") :].strip().strip('"').strip("'")
        if not version or not descriptors:
            continue
        for desc in descriptors:
            name = _yarn_name_from_descriptor(desc)
            if name:
                found.add((name, version))
        descriptors = []
    return sorted(found)


def parse_npm_lockfile(text: str, *, path: str = "") -> list[tuple[str, str]]:
    name = PurePosixPath(path.replace("\\", "/")).name.lower()
    if name == "pnpm-lock.yaml":
        return parse_pnpm_lock(text)
    if name == "yarn.lock":
        return parse_yarn_lock(text)
    return parse_package_lock(text)


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


def parse_lock(format: str, text: str, *, path: str = "") -> list[tuple[str, str]]:
    if format == "pypi":
        return parse_uv_lock(text)
    if format == "npm":
        return parse_npm_lockfile(text, path=path)
    if format == "nuget":
        return parse_nuget_lock(text)
    raise ValueError(f"Unsupported lock format: {format}")
