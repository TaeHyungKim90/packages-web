---
name: packages-web-project-packages
description: packages-web 과제별 패키지 현황 - 관리 대상 GHES 저장소의 락파일 수집, 패키지 집계, 반입일시(blobCreated), CVE 최고 점수, 필터·정렬 표준. Use when editing project_packages.py, lock_parsers.py, store_packages.py, routers/project_packages.py, or ProjectPackagesPage.
when_to_use: 락파일 후보 경로·파서 추가/수정 시. 과제별 패키지 동기화(sync) 로직 수정 시. 반입일시·CVE 점수 계산 수정 시. 과제별 패키지 화면의 필터/정렬/페이지 수정 시.
origin: packages-web
---

# packages-web Project Packages (과제별 패키지)

## 0. 흐름

```text
GET  /api/project-packages?org=&name=&format=&refresh_imported=&refresh_vulnerabilities=
     -> load_snapshot_cached()  (메모리 캐시 -> SQLite)
     -> (refresh_* 일 때만) attach_imported_at / build_vulnerability_index + attach_cve_scores -> 저장
     -> filter_aggregated
POST /api/project-packages/sync?org=
     -> collect_projects -> aggregate_by_package -> attach_imported_at
     -> build_vulnerability_index -> attach_cve_scores -> _persist_snapshot
```

- 권한은 `require_sk_inc`. 프론트는 "관리 > 과제별 패키지".
- **기본 GET은 외부 호출을 하지 않는다.** 테스트(`test_project_packages_get_from_cache`)가 GET에서 proxy-health 호출이 없음을 확인한다.
- 저장 후에는 반드시 `_persist_snapshot()`(저장 + `invalidate_snapshot_cache()`)을 쓴다. `save_snapshot`만 부르면 메모리 캐시가 낡는다.

## 1. 수집 (`collect_projects`)

- 대상: `ghes_inventory.load_yaml()` 중 `managed=True` 조직의 저장소. `org` 필터가 없는 조직이면 `ValueError` → 400.
- `org` 지정 동기화는 해당 조직만 다시 모으고 나머지 조직은 이전 스냅샷을 유지한다.
- 동시성: `GHES_CONCURRENCY = 5` 세마포어.
- 락파일 후보(`LOCK_CANDIDATES`), 디렉터리 `""`, `backend/`, `frontend/`:

| format | 파일 |
| --- | --- |
| pypi | `uv.lock` |
| npm | `package-lock.json`, `pnpm-lock.yaml`, `yarn.lock` |
| nuget | 저장소 이름에 `dotnet`이 들어간 경우에만 `packages.lock.json`을 재귀 검색 |

- 같은 저장소의 **같은 디렉터리 + 같은 format**에 락파일이 여럿이면(예: `frontend/package-lock.json`과 `frontend/pnpm-lock.yaml`) 기본 브랜치 마지막 커밋 시각이 가장 늦은 1개만 쓴다(`select_latest_locks`, `github.latest_commit_at`). 시각이 없는 파일은 밀리고, 그룹 전체 시각을 못 구하면 모두 유지하고 `errors`에 남긴다. 다른 디렉터리(`frontend/`와 루트)는 따로 유지한다.
- 이전 스냅샷과 파일 `sha`가 같으면 파싱을 건너뛰고 이전 결과를 재사용한다.
- 저장소 단위 오류는 `RepoSnapshot.errors`에 모으고 전체 동기화를 실패시키지 않는다.

## 2. 락파일 파서 (`lock_parsers.py`)

- 진입점은 `parse_lock(format, text, path=...)` 하나. 결과는 정렬된 `list[(name, version)]`.
- npm은 파일명으로 분기(`parse_npm_lockfile`): pnpm / yarn / package-lock(v1 legacy 포함).
- nuget은 `type == "project"` 의존성을 제외하고 `resolved` 버전을 쓴다.
- 새 락파일 형식은 파서 함수 + `parse_lock` 분기 + `LOCK_CANDIDATES` + `backend/tests/test_lock_parsers.py` 픽스처를 함께 추가한다.

## 3. 집계와 부가 정보

- 집계 키: `(format, name, version)`, 값: 사용 조직 목록(`str.lower` 정렬). 행 정렬은 `(format, name.lower(), version)`.
- 반입일시: `attach_imported_at` → `nexus.blob_created_map`(Hosted 우선, 없으면 `*-proxy-health`). 매칭은 `import_name_key` 정규화 키.
- CVE 점수: `build_vulnerability_index`가 세 eco의 proxy-health 캐시를 보장(`ensure_all_proxy_health_cached`)한 뒤 `vulnerability_entry`를 다시 만든다. 행의 `max_threat_level`은 `(format, import_name_key(name), version)`로 찾는다.
- 저장 테이블: `package_snapshot_meta`, `lock_file`, `lock_package`, `repo_error`, `aggregated_package`, `aggregated_package_org`, `vulnerability_meta`, `vulnerability_entry`.

## 4. 프론트 (`ProjectPackagesPage.tsx`)

- 필터 입력값과 적용값(`applied*`)을 분리하고, 검색 버튼으로 적용한다. 필터: 조직, 이름, format, 위험도 구간(`ThreatBand`).
- 정렬 키(`HealthSortKey`): `name`, `importedAt`, CVE 점수. 반입일시 비교는 `utils/health.ts`의 `cmpImportedAt`(값 없는 행은 방향과 무관하게 뒤로), 동률은 이름순.
- 페이지 크기 `PAGE_SIZE = 20`, `utils/result.ts`의 `paginate`.
- 반입일시 표시는 `formatImportedAt`, 없으면 `-`.
