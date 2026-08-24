import httpx
from fastapi import HTTPException

# Nexus auth/permission failures and redirects must not look like app session 401.
_MAP_TO_BAD_GATEWAY = frozenset({401, 403, 301, 302, 303, 307, 308})


def nexus_http_exception(exc: httpx.HTTPStatusError) -> HTTPException:
    status = exc.response.status_code
    if status in _MAP_TO_BAD_GATEWAY:
        status = 502
    return HTTPException(
        status_code=status,
        detail=f"Nexus API error: {exc.response.text[:500]}",
    )
