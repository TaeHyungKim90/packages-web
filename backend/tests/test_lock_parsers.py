from app.services.lock_parsers import (
    parse_nuget_lock,
    parse_package_lock,
    parse_uv_lock,
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


def test_parse_nuget_skips_project():
    rows = parse_nuget_lock(NUGET_LOCK)
    assert rows == [("Newtonsoft.Json", "13.0.3")]
