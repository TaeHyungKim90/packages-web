import httpx
from app.nexus_http import nexus_http_exception


def _status_error(status: int, text: str = "err") -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://nexus.example/")
    response = httpx.Response(status, text=text, request=request)
    return httpx.HTTPStatusError(str(status), request=request, response=response)


def test_nexus_401_maps_to_502():
    exc = nexus_http_exception(_status_error(401, "Unauthorized"))
    assert exc.status_code == 502
    assert "Nexus API error" in str(exc.detail)


def test_nexus_403_maps_to_502():
    exc = nexus_http_exception(_status_error(403, "Forbidden"))
    assert exc.status_code == 502


def test_nexus_302_maps_to_502():
    exc = nexus_http_exception(_status_error(302, "redirect"))
    assert exc.status_code == 502


def test_nexus_500_passthrough():
    exc = nexus_http_exception(_status_error(500, "boom"))
    assert exc.status_code == 500
    assert "boom" in str(exc.detail)
