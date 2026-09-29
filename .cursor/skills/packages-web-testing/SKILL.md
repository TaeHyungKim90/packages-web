---
name: packages-web-testing
description: packages-web 테스트·린트·CI 표준 - pytest(격리 SQLite, 세션 쿠키 주입, monkeypatch로 외부 호출 차단), vitest, ruff, Makefile 타깃, GitHub Actions. Use when writing or fixing tests in backend/tests or frontend/src/**/*.test.ts, changing Makefile targets, or editing .github/workflows/ci.yml.
when_to_use: backend/tests/** 신규/수정 시. frontend/src/**/*.test.ts 신규/수정 시. Makefile, .github/workflows/ci.yml, backend/pyproject.toml의 ruff/pytest 설정 수정 시. 기능 변경 후 검증 시.
origin: packages-web
---

# packages-web Testing

## 0. 명령

| 명령 | 내용 |
| --- | --- |
| `make lint-backend` | `uv run ruff check .` (E, F, I, UP, B / line-length 100 / py312) |
| `make lint-frontend` | `eslint . && tsc --noEmit` |
| `make type-check` | `npx tsc --noEmit -p tsconfig.json` |
| `make test-backend` | `uv run pytest` (`asyncio_mode = "auto"`, `testpaths = ["tests"]`) |
| `make test-frontend` | `vitest run` |
| `make check` | lint + test |

CI(`.github/workflows/ci.yml`)는 self-hosted 러너 + `cloud-ops-builder` 컨테이너에서 `uv sync --frozen`, `npm ci` 후 `make lint` → `make type-check` → `make test`를 돌린다. 로컬에서 같은 순서로 통과시킨 뒤 커밋한다.

## 1. 백엔드 원칙

- **외부 네트워크(Nexus, GHES, OSV, NVD, PyPI/npm/NuGet)를 실제로 호출하지 않는다.** `monkeypatch.setattr("app.services.<module>.<func>", fake)`로 바꾼다. 비동기 함수는 `async def` 가짜로 바꾼다.
- 가짜는 **사용되는 모듈 경로**에 건다. 예: `project_packages`가 import한 함수는 `app.services.project_packages.ensure_all_proxy_health_cached`.
- DB: `conftest.py`의 autouse 픽스처 `isolated_sqlite_db`가 테스트마다 `tmp_path/test.sqlite3`로 `settings.packages_web_db_path`를 바꾸고 `init_schema()`를 호출한다. 실제 `config/packages-web.sqlite3`를 건드리는 테스트를 만들지 않는다.
- 모듈 전역 캐시(`project_packages._snapshot_cache`)를 쓰는 경로는 `load_snapshot_cached`를 monkeypatch하거나 `invalidate_snapshot_cache()`를 호출해 테스트 간 오염을 막는다.
- 설정값은 `monkeypatch.setattr("app.config.settings.<field>", value)`.
- `async` 테스트 함수는 데코레이터 없이 `async def test_...`로 쓴다.

## 2. API 테스트

```python
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

def _authed(login: str = "sk-inc") -> TestClient:
    res = Response()
    set_session_cookie(res, SessionUser(login=login, name=login, avatar_url=None))
    value = res.headers["set-cookie"].split("=", 1)[1].split(";", 1)[0]
    client.cookies.set(settings.session_cookie_name, value)
    return client
```

- 권한 있는 엔드포인트마다 세 케이스를 둔다: 쿠키 없음 401, 다른 계정 403, 정상 200.
- owner 판정이 필요한 경우 `app.services.github.is_org_owner`를 monkeypatch한다.
- 테스트 시작 시 `client.cookies.clear()`로 이전 쿠키를 지운다.

## 3. 파일 배치

| 대상 | 파일 |
| --- | --- |
| 라우터/권한 | `test_<domain>_api.py` (`test_api.py`, `test_ghes_orgs_api.py`, `test_project_packages_api.py`) |
| 서비스 로직 | `test_<module>.py` (`test_gitops.py`, `test_osv.py`, `test_lock_parsers.py`, `test_proxy_health_store.py` 등) |
| 순수 헬퍼 | `test_nexus_helpers.py`, `test_nexus_http.py`, `test_session.py` |

- 새 동작은 기존 파일에 추가하고, 새 모듈을 만들었을 때만 새 테스트 파일을 만든다.
- 락파일·YAML 픽스처는 테스트 안의 문자열 리터럴로 둔다.

## 4. 프론트

- vitest, 순수 함수 위주: `utils/health.test.ts`, `utils/result.test.ts`, `api/client.test.ts`.
- 정렬·필터·표시 규칙을 바꾸면 해당 `utils/*.test.ts`에 케이스를 추가한다.
- `client.test.ts`는 현재 로그인 URL 생성만 검증한다. `apiFetch` 동작(401/3xx 리다이렉트, `credentials`)을 테스트할 때는 `vi.stubGlobal("fetch", ...)`로 `fetch`를 가짜로 바꾼다.
