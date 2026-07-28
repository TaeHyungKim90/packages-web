import pytest
from app.services.gitops import RequestRejected, _inventory_has, merge_request_package


def test_merge_adds_new_package():
    doc = {"ecosystem": "pypi", "packages": []}
    out = merge_request_package(doc, name="requests", version="2.32.3")
    assert out["packages"] == [{"name": "requests", "versions": ["2.32.3"]}]


def test_merge_appends_version():
    doc = {
        "ecosystem": "pypi",
        "packages": [{"name": "requests", "versions": ["2.31.0"]}],
    }
    out = merge_request_package(doc, name="requests", version="2.32.3")
    assert out["packages"][0]["versions"] == ["2.31.0", "2.32.3"]


def test_merge_rejects_duplicate_version():
    doc = {
        "ecosystem": "pypi",
        "packages": [{"name": "requests", "versions": ["2.32.3"]}],
    }
    with pytest.raises(RequestRejected):
        merge_request_package(doc, name="requests", version="2.32.3")


def test_inventory_has_versions_list():
    raw = """
packages:
  - name: requests
    versions: ["2.32.3", "2.31.0"]
"""
    assert _inventory_has(raw, "requests", "2.32.3") is True
    assert _inventory_has(raw, "requests", "9.9.9") is False


def test_inventory_has_scoped_string():
    raw = """
packages:
  - "@scope/pkg@1.2.3"
  - lodash@4.17.21
"""
    assert _inventory_has(raw, "@scope/pkg", "1.2.3") is True
    assert _inventory_has(raw, "@scope/pkg", "9.9.9") is False
    assert _inventory_has(raw, "lodash", "4.17.21") is True


def test_inventory_has_scoped_dict():
    raw = """
packages:
  - name: "@scope/pkg"
    versions: ["1.2.3"]
"""
    assert _inventory_has(raw, "@scope/pkg", "1.2.3") is True
    assert _inventory_has(raw, "@scope/pkg", "0.0.1") is False


def test_merge_scoped_npm_package():
    doc = {"ecosystem": "npm", "packages": []}
    out = merge_request_package(doc, name="@scope/pkg", version="1.2.3")
    assert out["packages"] == [{"name": "@scope/pkg", "versions": ["1.2.3"]}]


def test_requests_has():
    from app.services.gitops import _requests_has

    doc = {
        "ecosystem": "pypi",
        "packages": [{"name": "requests", "versions": ["2.32.3"]}],
    }
    assert _requests_has(doc, "requests", "2.32.3") is True
    assert _requests_has(doc, "requests", "9.9.9") is False
    assert _requests_has(doc, "urllib3", "2.0.0") is False
