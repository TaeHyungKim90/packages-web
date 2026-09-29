---
name: packages-web-ghes-inventory
description: packages-web GHES 조직·저장소 인벤토리(관리 대상 지정)와 GHES 가입자 목록 동기화 표준. Use when editing ghes_inventory.py, ghes_models.py, store_orgs.py, ghes_members.py, routers/ghes_inventory.py, routers/ghes_members.py, GhesOrgsPage, or GhesMembersPage.
when_to_use: GHES 조직/저장소 동기화·저장 로직 수정 시. managed/present 플래그 처리 변경 시. GHES 가입자 수집·필터 규칙 변경 시. 레거시 config/ghes-orgs.yaml 이관 관련 작업 시.
origin: packages-web
---

# packages-web GHES Inventory & Members

## 0. 공통

- 모든 API는 `require_sk_inc`(sk-inc 관리 계정)만 쓴다. 프론트는 `RequireOrgsAccess`, 메뉴는 "관리".
- **GET은 DB만 읽는다. GHES 호출은 `POST .../sync`에서만** 한다. GET에 live 조회를 넣지 않는다.
- `GitHubError`는 503이면 503, 나머지 502로 바꾼다.
- GHES API 호출은 `services/github.py`의 함수(`list_all_organizations`, `list_org_repos`, `_api`, `_headers`)를 재사용한다.

## 1. 조직 인벤토리

```text
GET  /api/ghes-orgs       -> list_cached_inventory()          (DB, synced_at)
POST /api/ghes-orgs/sync  -> sync_inventory()                 (GHES live + DB managed 병합 후 저장)
PUT  /api/ghes-orgs       -> save_yaml(stored)                (managed 플래그 저장)
```

- 모델(`ghes_models.py`): 저장용 `StoredOrg`/`StoredRepo`, 화면용 `InventoryOrg`/`InventoryRepo`. 둘 다 `name`, `managed`, `present`.
- `managed`: 관리자가 지정한 관리 대상 여부. 과제별 패키지 수집 대상은 `managed=True` 조직의 저장소다(`project_packages.list_managed_projects`).
- `present`: GHES에 현재 존재하는지. live에서 사라진 조직/저장소는 삭제하지 않고 `present=False`로 남겨 managed 설정을 보존한다(`merge_with_yaml`).
- PUT은 기존 캐시의 `present` 값을 이름 기준으로 유지한다.
- 정렬은 이름 `str.lower` 기준.
- 함수 이름 `load_yaml` / `save_yaml` / `merge_with_yaml`은 이력상 이름이고 실제 저장소는 SQLite(`store_orgs.load_orgs`, `save_orgs`)다. 새 코드에서 YAML 파일을 읽거나 쓰지 않는다.
- 테이블: `ghes_org`, `ghes_repo`, `ghes_inventory_meta(synced_at)`.

## 2. GHES 가입자

```text
GET  /api/ghes-members       -> list_cached_members()   (DB)
POST /api/ghes-members/sync  -> sync_members()          (GHES 사용자·조직 멤버 수집 후 저장)
```

- 사람 계정만 나열한다: `SKIP_USER_TYPES = {"organization", "bot"}`, `SKIP_LOGINS = {"actions-admin", "ghost"}`. 필터 변경은 `_is_person_account`와 `_should_list_member`를 함께 수정한다.
- 소속 조직 표시는 `_organizations_label`: 관리 계정(`settings.ghes_inventory_login`)은 `관리`, 나머지는 조직명 콤마 목록. `sk-inc` 조직(`SKIP_ORG`)은 소속 목록에서 뺀다.
- 테이블: `ghes_member`, `ghes_member_org`, `ghes_member_meta(synced_at)`.
- 화면은 `GhesMembersPage`, 엑셀 내보내기(`xlsx`) 포함.

## 3. 레거시 YAML 이관

- `config/ghes-orgs.yaml`은 `db.migrate_yaml_if_needed()`가 앱 시작 시 한 번만 SQLite로 옮긴다(`meta.yaml_migrated=1`).
- 이관 파서는 `ghes_inventory._parse_org`를 재사용한다. 이 함수 시그니처를 바꾸면 `db._migrate_orgs_yaml`도 확인한다.

## 4. 테스트

- `backend/tests/test_ghes_inventory.py`(병합 규칙), `test_ghes_orgs_api.py`(API/권한), `test_ghes_members.py`(필터·라벨).
- GHES 호출은 `monkeypatch`로 `app.services.github.list_all_organizations` 등을 async 가짜 함수로 바꾼다.
