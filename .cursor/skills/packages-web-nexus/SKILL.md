---
name: packages-web-nexus
description: packages-web의 Nexus Repository 연동 표준(Hosted 검색, 업스트림 버전 존재 확인, blobCreated 반입일시, 이름 정규화). Use when editing backend/app/services/nexus.py, calling the Nexus search REST API, checking whether a package version exists upstream, or matching package names across pypi/npm/nuget.
when_to_use: backend/app/services/nexus.py 수정 시. Nexus /service/rest/v1/search 호출 추가 시. 업스트림(PyPI/npm/NuGet) 버전 확인 로직 수정 시. 반입일시(imported_at) 계산 수정 시. 패키지 이름 비교 로직 작성 시.
origin: packages-web
---

# packages-web Nexus

## 0. 기본 규칙

- Nexus 호출은 `backend/app/services/nexus.py`(검색·버전·반입일시)와 `nexus_health.py`(Health Check 리포트)에만 둔다.
- 인증은 `_auth()`(Basic, `NEXUS_USERNAME`/`NEXUS_PASSWORD`), SSL은 `settings.nexus_verify_ssl`.
- 검색 API는 `SEARCH_PATH = "/service/rest/v1/search"`. 404는 빈 결과(`{"items": []}`)로 본다.
- 페이지네이션은 `continuationToken`을 따라가되 상한을 둔다(`MAX_CHECK_PAGES = 5`, `MAX_BLOB_PAGES = 20`).
- 병렬 조회는 `asyncio.Semaphore`로 제한한다(`BLOB_SEARCH_CONCURRENCY = 8`).
- 라우터에서 오류를 바꿀 때는 `nexus_http_exception`을 쓴다. `packages-web-fastapi-routing` 참조.

## 1. 이름 정규화

패키지를 비교·키로 쓸 때는 항상 `import_name_key(name, fmt)`를 거친다.

| fmt | 규칙 |
| --- | --- |
| pypi | PEP 503: `normalize_pypi_name` (`[-_.]+` → `-`, 소문자) |
| npm / nuget | `strip().lower()` |

- `(format, import_name_key(name, format), version)` 3-튜플이 취약점 인덱스·반입일시 매칭의 공통 키다.
- npm scoped 이름(`@scope/pkg`)은 검색 시 `_search_name_params`가 `group=scope`, `name=pkg`로 나눈다. URL에 넣을 때는 `/`를 `%2F`로 인코딩한다.
- NuGet은 flat-container URL에서 id와 version을 모두 소문자로 쓴다.

## 2. Hosted 조회

- `check_package(repository, package_format, name, version, continuation_token)` — 화면 검색용. 이름 부분 일치, 버전 정확/부분 일치.
- `default_hosted_for_format(fmt)` → `ECOSYSTEM_MAP[fmt].hosted_repo`.
- 신청 검증의 "이미 등록됨"은 `gitops.hosted_has_exact()`(이름 대소문자 무시 + 버전 정확 일치)를 쓴다.

## 3. 업스트림 버전 존재 (`upstream_version_exists`)

공개 레지스트리를 먼저 보고, 사내망에서 막히면 Nexus proxy로 넘어간다.

| fmt | 1순위 | 폴백 |
| --- | --- | --- |
| pypi | `pypi.org` JSON (`True`일 때만 확정) | proxy `/simple/{project}/` HTML에서 wheel/sdist 파일명 버전 파싱 |
| npm | `registry.npmjs.org/{name}/{version}` | 404/접속 실패 시 proxy 메타데이터의 `versions` |
| nuget | `api.nuget.org` flat-container (`True`/`False` 확정) | `None`(접속 불가)일 때만 proxy |

- proxy 조회는 로컬 캐시 목록이 아니라 캐시 미스 시 원격을 당겨오는 용도다. 이 전제를 깨는 "Hosted 검색으로 대체" 같은 변경을 하지 않는다.
- 미지원 fmt는 `ValueError`.

## 4. 반입일시 (`blob_created_map`)

- 입력: `keys: set[(name, version)]`, `hosted_repo`, `health_repo`. 출력: `({(name_key, version): iso}, hosted_keys)`.
- Hosted에서 먼저 찾고, 없는 버전만 `*-proxy-health`에서 찾는다.
- 값은 컴포넌트/asset의 `blobCreated` 중 최신, 없으면 `lastModified`. 숫자는 ms/초 모두 처리하고 결과는 UTC ISO 문자열.
- 사용처: `nexus_health._attach_import_status`(취약점 `imported_at`, `in_hosted`), `project_packages.attach_imported_at`(과제별 패키지 반입일시 정렬).

## 5. 테스트

- 순수 함수(`normalize_pypi_name`, `simple_index_has_version`, `item_blob_created`, `import_name_key`)는 `backend/tests/test_nexus_helpers.py`에 단위 테스트한다.
- HTTP는 실제로 호출하지 않는다. `monkeypatch`로 `app.services.nexus.<func>`를 async 가짜 함수로 바꾼다.
