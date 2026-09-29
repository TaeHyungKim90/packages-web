---
name: packages-web-config-schemas
description: packages-web 설정(ECOSYSTEM_MAP, Settings), Pydantic 응답 스키마, SQLite 스키마 변경 표준. Use when adding an ecosystem or repository mapping, a new environment variable, a request/response model in backend/app/schemas.py, or a table/column in backend/app/db.py.
when_to_use: backend/app/config.py 수정 시. .env.example 수정 시. backend/app/schemas.py 신규 모델 추가 시. backend/app/db.py SCHEMA_SQL/init_schema 변경 시. frontend/src/types.ts와 응답 형상 동기화 시.
origin: packages-web
---

# packages-web Config & Schemas

## 1. ECOSYSTEM_MAP (`backend/app/config.py`)

eco별 Nexus 저장소와 GitOps 파일 매핑의 **유일한 원천**이다.

```python
"pypi": EcosystemConfig(
    ecosystem="pypi",
    hosted_repo="pypi-hosted",
    proxy_repo="pypi-proxy",
    health_repo="pypi-proxy-health",
    gitops_repo="pypiPackages",
    requests_file="requests/pypi_requests_list.yaml",
    inventory_file="inventory/pypi_last_list.yaml",
),
```

- 조회는 `settings.get_ecosystem(key)`(미지원이면 `ValueError`) 또는 `ECOSYSTEM_MAP.get(fmt)`.
- 새 eco 추가 시 함께 바꿀 곳: `ECOSYSTEM_MAP`, 라우터의 `SUPPORTED` 집합, `nexus.upstream_version_exists`, `osv.ECOSYSTEM_OSV`, `lock_parsers.parse_lock`, 프론트 `PackageType`·`Header.tsx`의 `ECOSYSTEMS`·`App.tsx` 라우트.

## 2. Settings

- `pydantic-settings`의 `Settings`이며 `.env`와 `../.env`를 읽는다(`backend/`에서 실행해도 루트 `.env` 사용).
- 새 설정은 snake_case 필드 + 기본값으로 추가하고, 같은 커밋에서 루트 `.env.example`에 대문자 키로 추가한다.
- 콤마 리스트는 `Annotated[list[str], NoDecode]` + `field_validator(mode="before")` 패턴(`cors_origins` 참조).
- 사내망 전제 기본값을 유지한다: `osv_verify_ssl=False`(MITM), 내부 GHES/Nexus URL.
- 코드에서는 `from app.config import settings` 싱글턴만 쓴다. 테스트에서는 `monkeypatch.setattr("app.config.settings.<field>", ...)`.
- `.env` 자체는 사용자 승인 없이 수정하지 않는다.

## 3. Pydantic 스키마 (`backend/app/schemas.py`)

- API 경계 모델은 모두 이 파일에 둔다. 도메인별 파일로 쪼개지 않는다.
- 네이밍: 응답 `*Response` / `*Result` / `*Status`, 요청 본문 `*Body` / `*Update`, 행 `*Item` / `*Row`.
- 필드는 snake_case 그대로 JSON에 노출한다(alias 없음). 예외는 쿼리 파라미터 `continuationToken`처럼 외부 API 이름을 따르는 경우만.
- 서비스 내부 자료구조는 `@dataclass`(`project_packages.AggregatedRow`, `ghes_models.StoredOrg`)이고, 라우터의 `_to_items()` / `_to_response()`에서 스키마로 변환한다.
- 스키마를 바꾸면 `frontend/src/types.ts`의 대응 타입도 같은 커밋에서 수정한다.

## 4. SQLite 스키마 (`backend/app/db.py`)

- DB 파일: `settings.packages_web_db_path`, 비어 있으면 `<repo>/config/packages-web.sqlite3`.
- `connect()`는 `row_factory=sqlite3.Row`, `foreign_keys=ON`, `journal_mode=WAL`을 켠다. 직접 `sqlite3.connect`를 쓰지 않는다.
- 새 테이블: `SCHEMA_SQL`에 `CREATE TABLE IF NOT EXISTS`로 추가.
- 기존 테이블에 컬럼 추가: `SCHEMA_SQL`의 정의 **와** `init_schema()`의 `_ensure_column(conn, table, column, ddl)`을 둘 다 추가한다. 운영 중인 DB 파일은 `CREATE TABLE IF NOT EXISTS`로 갱신되지 않는다.
- 컬럼 삭제·이름 변경은 하지 않는다(마이그레이션 도구 없음). 필요하면 사용자와 먼저 상의한다.
- bool은 `INTEGER NOT NULL DEFAULT 0`, 시각은 ISO 8601 UTC 문자열 `TEXT`.
- 스키마 의미가 바뀌면 `SCHEMA_VERSION`을 올린다.
- `config/*.yaml`(ghes-orgs, ghes-project-packages, ghes-package-vulnerabilities)은 레거시 이관 원본이다. `migrate_yaml_if_needed()`가 한 번만 읽고 `meta.yaml_migrated=1`을 남긴다. 새 기능에서 YAML에 쓰지 않는다.
