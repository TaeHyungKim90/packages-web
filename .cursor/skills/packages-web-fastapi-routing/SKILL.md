---
name: packages-web-fastapi-routing
description: packages-web 백엔드 FastAPI 라우터·의존성·오류 매핑 표준. Use when adding or editing routes under backend/app/routers, registering routers in backend/main.py, choosing auth dependencies from backend/app/deps.py, or mapping Nexus/GitHub errors to HTTP status codes.
when_to_use: backend/app/routers/** 신규/수정 시. backend/main.py 라우터 등록 시. backend/app/deps.py, backend/app/nexus_http.py 수정 시. 새 API endpoint 추가 시.
origin: packages-web
---

# packages-web FastAPI Routing

## 0. 기본 규칙

- 라우터 파일은 `backend/app/routers/<domain>.py`에 두고 모듈 레벨에 `router = APIRouter(prefix="/<path>", tags=["<tag>"])`를 노출한다.
- 새 라우터는 `backend/main.py`에 **직접** 등록한다. 모든 API는 `/api` 접두사를 쓴다.

```python
from app.routers import new_domain
app.include_router(new_domain.router, prefix="/api")
```

- 라우터는 입력 정규화, 권한 의존성, 예외를 HTTP로 바꾸는 일만 한다. 외부 호출·가공·저장은 `backend/app/services/`에 둔다.
- 요청/응답 모델은 `backend/app/schemas.py`의 Pydantic 모델을 `response_model=`로 지정한다.
- `/health`만 인증 없이 열려 있다. 나머지 엔드포인트는 모두 권한 의존성을 건다.

## 1. 권한 의존성 (`backend/app/deps.py`)

라우터 상단에 `Annotated` 별칭을 선언해 쓴다.

```python
CurrentUser = Annotated[SessionUser, Depends(require_user)]        # 로그인만
OwnerUser = Annotated[SessionUser, Depends(require_cicd_owner)]    # CICD org owner
CurrentUser = Annotated[SessionUser, Depends(require_sk_inc)]      # sk-inc 계정(관리)
```

| 의존성 | 실패 | 쓰는 곳 |
| --- | --- | --- |
| `require_user` | 401 | 패키지 검색, 취약점 조회 |
| `require_cicd_owner` | 401 / 403 | 패키지 신청 전체, 취약점 override PUT/DELETE |
| `require_sk_inc` | 401 / 403 | GHES 조직, GHES 가입자, 과제별 패키지 |

- 쓰지 않는 사용자 인자는 `_user`로 받는다.
- 권한 규칙을 바꾸면 `routers/auth.py`의 `/auth/me` 응답(`can_request`, `can_view_orgs`)과 프론트 게이트도 함께 맞춘다. `packages-web-ghes-auth` 참조.

## 2. eco 경로 파라미터

eco(`pypi | npm | nuget`)를 경로로 받는 라우터는 같은 모양을 유지한다.

```python
SUPPORTED = frozenset({"pypi", "npm", "nuget"})
EcoPath = Annotated[str, Path(description="Package ecosystem: pypi | npm | nuget")]

def _require_eco(eco: str) -> str:
    key = eco.lower().strip()
    if key not in SUPPORTED:
        raise HTTPException(status_code=400, detail=f"Unsupported ecosystem: {eco}. ...")
    return key
```

- 설정은 `settings.get_ecosystem(key)`로 가져온다. 저장소 이름을 라우터에 하드코딩하지 않는다.
- 기존 차이: `package_request.py`는 미지원 eco에 404, `proxy_health.py`는 400을 쓴다. 새 라우터는 400을 쓴다.

## 3. 오류 매핑

| 원인 | 변환 |
| --- | --- |
| `httpx.HTTPStatusError` (Nexus) | `raise nexus_http_exception(exc) from exc` — Nexus의 401/403/3xx는 502로 바꿔 **앱 세션 401과 구분** |
| `httpx.HTTPError` (Nexus 접속 실패) | 502 `"Failed to reach Nexus: ..."` |
| `GitHubError` | `exc.status_code == 503`이면 503, 404가 의미 있으면 404, 나머지 502 |
| `RequestRejected` (업무 규칙 거절) | 409 |
| `ProxyHealthUnavailable` | 502 |
| `LookupError` (DB 스냅샷 없음) | 404 |
| 입력 검증 실패 | 400 (한국어 `detail` 허용) |
| `settings.github_token` 미설정 | 503 `"GITHUB_TOKEN is not configured"` |

- 항상 `from exc`로 연결한다.
- 프론트 `api/client.ts`는 401과 3xx를 로그인 리다이렉트로 처리한다. 외부 시스템 인증 실패를 401로 돌려주면 사용자가 로그아웃되므로 금지한다.

## 4. SQLite 쓰기가 필요한 라우터

라우터에서 직접 쓰기를 해야 하면 `connect()` → 서비스 함수 → `commit()` → `finally: close()` 순서를 지킨다(`routers/proxy_health.py`의 override 참조). 가능하면 서비스 함수 안으로 옮긴다.

## 5. 체크리스트

- [ ] `main.py`에 `include_router(..., prefix="/api")` 추가
- [ ] 권한 의존성 지정, 프론트 게이트/메뉴와 일치
- [ ] `response_model` 지정, 스키마는 `schemas.py`
- [ ] Nexus/GitHub 예외 매핑, 401 누출 없음
- [ ] `backend/tests/test_<domain>_api.py`에 401/403/정상 케이스 추가
