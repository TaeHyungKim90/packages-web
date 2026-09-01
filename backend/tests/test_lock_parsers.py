from app.services.lock_parsers import (
    parse_nuget_lock,
    parse_package_lock,
    parse_pnpm_lock,
    parse_uv_lock,
    parse_yarn_lock,
)

UV_LOCK = """
version = 1

[[package]]
name = "fastapi"
version = "0.115.0"

[[package]]
name = "httpx"
version = "0.27.0"
"""

PACKAGE_LOCK = """
{
  "lockfileVersion": 3,
  "packages": {
    "": {"name": "app", "version": "1.0.0"},
    "node_modules/react": {"version": "19.2.7"},
    "node_modules/@scope/pkg": {"version": "1.2.3"}
  }
}
"""

PNPM_LOCK = """
lockfileVersion: '9.0'
packages:
  react@19.2.7:
    resolution: {integrity: sha512-aaa}
  /@scope/pkg@1.2.3:
    resolution: {integrity: sha512-bbb}
  /lodash@4.17.21(foo@1.0.0):
    resolution: {integrity: sha512-ccc}
"""

YARN_CLASSIC = """
# yarn lockfile v1

react@^19.0.0:
  version "19.2.7"
  resolved "https://registry.npmjs.org/react/-/react-19.2.7.tgz"

"@scope/pkg@^1.0.0":
  version "1.2.3"
  resolved "https://registry.npmjs.org/@scope/pkg/-/pkg-1.2.3.tgz"
"""

YARN_BERRY = """
__metadata:
  version: 6

"react@npm:^19.0.0":
  version: 19.2.7
  resolution: "react@npm:19.2.7"

"@scope/pkg@npm:^1.0.0":
  version: 1.2.3
  resolution: "@scope/pkg@npm:1.2.3"
"""

NUGET_LOCK = """
{
  "version": 1,
  "dependencies": {
    "net8.0": {
      "Newtonsoft.Json": {
        "type": "Direct",
        "resolved": "13.0.3"
      },
      "Local.Lib": {
        "type": "Project"
      }
    }
  }
}
"""


def test_parse_uv_lock():
    rows = parse_uv_lock(UV_LOCK)
    assert ("fastapi", "0.115.0") in rows
    assert ("httpx", "0.27.0") in rows


def test_parse_package_lock_flat():
    rows = parse_package_lock(PACKAGE_LOCK)
    assert ("react", "19.2.7") in rows
    assert ("@scope/pkg", "1.2.3") in rows
    names = {n for n, _ in rows}
    assert "app" not in names or ("app", "1.0.0") not in rows


def test_parse_pnpm_lock():
    rows = parse_pnpm_lock(PNPM_LOCK)
    assert ("react", "19.2.7") in rows
    assert ("@scope/pkg", "1.2.3") in rows
    assert ("lodash", "4.17.21") in rows


def test_parse_yarn_classic():
    rows = parse_yarn_lock(YARN_CLASSIC)
    assert ("react", "19.2.7") in rows
    assert ("@scope/pkg", "1.2.3") in rows


def test_parse_yarn_berry():
    rows = parse_yarn_lock(YARN_BERRY)
    assert ("react", "19.2.7") in rows
    assert ("@scope/pkg", "1.2.3") in rows


def test_parse_nuget_skips_project():
    rows = parse_nuget_lock(NUGET_LOCK)
    assert rows == [("Newtonsoft.Json", "13.0.3")]
