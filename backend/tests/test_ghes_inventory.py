from pathlib import Path

from app.services.ghes_inventory import (
    StoredOrg,
    StoredRepo,
    load_yaml,
    merge_with_yaml,
    save_yaml,
)


def test_merge_applies_managed_and_keeps_orphans():
    live = {
        "CICD": ["pypiPackages", "newRepo"],
        "Other": ["r1"],
    }
    stored = [
        StoredOrg(
            name="CICD",
            managed=True,
            repos=[
                StoredRepo(name="pypiPackages", managed=True),
                StoredRepo(name="goneRepo", managed=True),
            ],
        ),
        StoredOrg(name="OnlyYaml", managed=False, repos=[]),
    ]
    merged = merge_with_yaml(live, stored)
    by_name = {o.name: o for o in merged}

    assert by_name["CICD"].managed is True
    assert by_name["CICD"].present is True
    repos = {r.name: r for r in by_name["CICD"].repos}
    assert repos["pypiPackages"].managed is True and repos["pypiPackages"].present
    assert repos["newRepo"].managed is False and repos["newRepo"].present
    assert repos["goneRepo"].managed is True and not repos["goneRepo"].present

    assert by_name["Other"].managed is False
    assert by_name["OnlyYaml"].present is False


def test_load_yaml_accepts_legacy_string_repos(tmp_path: Path):
    path = tmp_path / "orgs.yaml"
    path.write_text(
        "organizations:\n"
        "  - name: CICD\n"
        "    repos:\n"
        "      - pypiPackages\n",
        encoding="utf-8",
    )
    orgs = load_yaml(path)
    assert len(orgs) == 1
    assert orgs[0].name == "CICD"
    assert orgs[0].managed is False
    assert orgs[0].repos[0].name == "pypiPackages"
    assert orgs[0].repos[0].managed is False


def test_save_and_load_roundtrip(tmp_path: Path):
    path = tmp_path / "orgs.yaml"
    save_yaml(
        [
            StoredOrg(
                name="CICD",
                managed=True,
                repos=[StoredRepo(name="pypiPackages", managed=True)],
            )
        ],
        path=path,
    )
    loaded = load_yaml(path)
    assert loaded[0].managed is True
    assert loaded[0].repos[0].managed is True
