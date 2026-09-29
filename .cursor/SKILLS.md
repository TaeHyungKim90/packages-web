# packages-web 작업별 skill

Nexus Hosted 검색, PyPI/npm/NuGet 패키지 신청(GitOps PR), 프록시 보안 취약점, GHES 관리 화면을 제공하는 웹 도구다.

- Backend: Python 3.12+ / FastAPI / pydantic-settings / httpx / SQLite(`sqlite3` 직접 사용) / itsdangerous 세션
- Frontend: React 19 + TypeScript / Vite / react-router v8 / vitest
- CI: GitHub Actions self-hosted (`make lint`, `make type-check`, `make test`)

## 구조 전제 (ADT와 다른 점)

- 백엔드는 `backend/app/routers/` + `backend/app/services/` **플랫 구조**다. domain/application/infrastructure 계층, Port/UseCase, `*Entity` 네이밍을 도입하지 않는다.
- 라우터는 `backend/main.py`에서 `app.include_router(x.router, prefix="/api")`로 **수동 등록**한다. `discover_routers()` 같은 자동 등록은 없다.
- DB는 SQLAlchemy/Alembic이 아니라 `backend/app/db.py`의 `SCHEMA_SQL` + `_ensure_column()`이다.
- Celery, S3, EKS, LLM 관련 작업은 이 저장소에 없다.

## 작업별 skill

해당 영역을 수정할 때 `.cursor/skills/<name>/SKILL.md`를 읽고 적용한다.

| 작업 영역 | Skill |
| --- | --- |
| `backend/app/routers/**`, `backend/main.py`, `backend/app/deps.py`, `backend/app/nexus_http.py` | `packages-web-fastapi-routing` |
| `backend/app/config.py`(`ECOSYSTEM_MAP`, `Settings`), `backend/app/schemas.py`, `backend/app/db.py` 스키마, `.env.example` | `packages-web-config-schemas` |
| `backend/app/services/nexus.py`, Hosted 검색, 업스트림 버전 확인, `blobCreated` | `packages-web-nexus` |
| `backend/app/services/gitops.py`, `backend/app/services/github.py`, `routers/package_request.py`, 신청 페이지 | `packages-web-package-request` |
| GHES OAuth 로그인, 세션 쿠키, `require_*` 권한 게이트, `AuthGate.tsx`, `useAuth` | `packages-web-ghes-auth` |
| `nexus_health.py`, `osv.py`, `proxy_health_store.py`, `routers/proxy_health.py`, 취약점 페이지 | `packages-web-proxy-health` |
| `ghes_inventory.py`, `ghes_members.py`, `store_orgs.py`, `ghes_models.py`, GHES 조직/가입자 페이지 | `packages-web-ghes-inventory` |
| `project_packages.py`, `lock_parsers.py`, `store_packages.py`, 과제별 패키지 페이지 | `packages-web-project-packages` |
| `frontend/src/**` (페이지, 라우트, 메뉴, `api/client.ts`, 스타일) | `packages-web-frontend` |
| `backend/tests/**`, `frontend/src/**/*.test.ts`, `Makefile`, `.github/workflows/ci.yml` | `packages-web-testing` |

## 필수 규칙

- 새 eco(패키지 포맷)나 저장소·GitOps 파일 매핑은 `ECOSYSTEM_MAP` 한곳에만 추가한다. 라우터·서비스에 `"pypi-hosted"` 같은 문자열을 새로 흩뿌리지 않는다.
- 새 엔드포인트는 반드시 `require_user` / `require_cicd_owner` / `require_sk_inc` 중 하나로 보호하고, 프론트 라우트 게이트·메뉴 노출과 맞춘다.
- DB 컬럼 추가는 `SCHEMA_SQL`과 `init_schema()`의 `_ensure_column()`을 **둘 다** 수정한다(기존 SQLite 파일 호환).
- 변경 후 `make check`(lint + test)를 실행한다. 프론트를 건드렸으면 `make type-check`도 실행한다.
- `.env` 수정 전에는 사용자 승인을 받는다. 새 설정은 `Settings`와 `.env.example`에 함께 추가한다.
- `git push` 전에는 포함될 커밋을 사용자에게 보고하고 승인을 받는다.

## 핵심 명령어

```bash
make install        # uv sync + npm install
make dev            # backend :8000 + frontend :5173
make lint           # ruff + eslint/tsc
make type-check     # tsc --noEmit
make test           # pytest + vitest
make check          # lint + test
```
