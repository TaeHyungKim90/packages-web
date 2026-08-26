from app.services.ghes_inventory import (
    _parse_org,
    load_yaml,
    merge_with_yaml,
)
from app.services.ghes_models import StoredOrg, StoredRepo
from app.services.store_orgs import load_orgs, save_orgs


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


def test_parse_org_accepts_legacy_string_repos():
    org = _parse_org(
        {
            "name": "CICD",
            "repos": ["pypiPackages"],
        }
    )
    assert org is not None
    assert org.name == "CICD"
    assert org.managed is False
    assert org.repos[0].name == "pypiPackages"
    assert org.repos[0].managed is False


def test_save_and_load_roundtrip():
    save_orgs(
        [
            StoredOrg(
                name="CICD",
                managed=True,
                repos=[StoredRepo(name="pypiPackages", managed=True)],
            )
        ]
    )
    loaded = load_orgs()
    assert loaded[0].managed is True
    assert loaded[0].repos[0].managed is True
    assert load_yaml()[0].name == "CICD"
