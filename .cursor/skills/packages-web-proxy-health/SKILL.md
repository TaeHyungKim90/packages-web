---
name: packages-web-proxy-health
description: packages-web 프록시 저장소 보안 취약점(Nexus Repository Health Check) 조회, SQLite 캐시/TTL, OSV·NVD 해결 버전 보강, 취약점 override(해결 버전·비고·오탐) 표준. Use when editing nexus_health.py, osv.py, proxy_health_store.py, routers/proxy_health.py, ProxyHealthPage, VulnOverrideModal, or utils/health.ts.
when_to_use: 취약점/라이선스 리포트 조회·캐시 로직 수정 시. OSV fixed_version, published_at 보강 수정 시. override 저장/삭제 수정 시. 해결/오탐 판정(resolved) 변경 시. backend/scripts/refresh_osv_fixed_versions.py 수정 시. 취약점 화면·엑셀 내보내기 수정 시.
origin: packages-web
---

# packages-web Proxy Health (취약점)

## 0. 흐름

```text
GET /api/proxy-health/{eco}?refresh=     (require_user)
  owner 아님 -> get_proxy_health_from_db (DB만, 없으면 404)
  owner      -> get_proxy_health_cached(force_refresh=refresh)
                  캐시 유효 -> DB
                  만료/강제 -> nexus_health.fetch_proxy_health
                             -> apply_fixed_versions_from_index (DB에 있던 fixed 재사용)
                             -> osv.enrich_fixed_versions (없는 것만 OSV/NVD)
                             -> apply_vuln_overrides -> save_proxy_health_to_conn
                  Nexus 실패 + 캐시 있음 -> 이전 스냅샷 반환
GET /api/proxy-health/{eco}/snapshot     (require_user, DB만)
PUT|DELETE /api/proxy-health/{eco}/overrides   (require_cicd_owner)
```

- 반환 직전에는 항상 `_finalize_report(report, overrides)`로 override와 `resolved`를 반영한다. 새 반환 경로도 이 함수를 거친다.
- 외부(Nexus/OSV)를 부르는 경로는 owner live 조회뿐이다. 일반 사용자 요청이 외부 호출을 일으키게 만들지 않는다.

## 1. Nexus 리포트 (`nexus_health.py`)

- 후보 저장소: `health_repo`(`*-proxy-health`) 다음 `proxy_repo`(`_candidate_repos`). 둘 다 없으면 `ProxyHealthUnavailable` → 502.
- 메타 → 상세 디렉터리 → security/licenses JSON 순서로 조회한다. 매핑은 `map_vulnerability`, `map_license`.
- `generated_at`은 Nexus `lastAnalyzedDate`(분석 시각). `imported_at`, `in_hosted`는 `blob_created_map`으로 붙인다(`packages-web-nexus` 참조).

## 2. 캐시 / TTL (`proxy_health_store.py`)

| 기준 | 설정 | 기본 |
| --- | --- | --- |
| 리포트 분석 시각 `generated_at` | `proxy_health_report_ttl_seconds` | 86400 (24h) |
| 마지막 live 조회 `fetched_at` | `proxy_health_ttl_seconds` | 7200 (2h) |

- 둘 중 하나라도 유효하면 DB를 쓴다(`_should_use_cache`). `refresh=true`면 무시한다.
- 프론트 `useIdleReload`의 `IDLE_RELOAD_MS`(2h)는 `proxy_health_ttl_seconds` 기본값과 맞춰져 있다. 한쪽을 바꾸면 다른 쪽도 확인한다.
- 저장 테이블: `proxy_health_meta`, `proxy_health_vulnerability`, `proxy_health_license`, `proxy_health_vuln_override`.

## 3. 해결 버전 보강 (`osv.py`)

- `settings.osv_enabled=False`면 보강을 건너뛴다. SSL은 `osv_verify_ssl`(기본 False)로 시도하고, True면 False로 한 번 더 시도한다.
- 이미 유효한 `fixed_version`이 있거나 override 키(`(problem_code, artifact)`)가 있는 항목은 조회하지 않는다.
- OSV `fixed` 이벤트가 없으면 CVE/GHSA 관련 문서와 `extracted_events`를 보고, `last_affected`만 있으면 npm/PyPI에서 다음 안정 버전을 찾는다.
- `published_at`이 OSV에 없으면 NVD로 채운다(`nvd_enabled`, `nvd_api_key`).
- git 커밋 SHA는 해결 버전이 아니다. 저장·표시 전 `is_package_fixed_version`으로 거른다.
- 보강 실패는 로그만 남기고 원래 목록을 돌려준다. 예외로 API를 실패시키지 않는다.

## 4. override와 판정

- 키: `(ecosystem, problem_code, artifact)`. 값: `fixed_version`(선택), `remark`, `updated_at`.
- PUT은 `problem_code`, `artifact` 필수, `fixed_version`은 `is_package_fixed_version` 통과해야 한다(400).
- `resolved`(`is_resolved_or_false_positive`)는 다음이면 True:
  - `remark` 또는 `fixed_version`에 `오탐`, `해당 없음`, `false positive`, `N/A`
  - 현재 버전이 해결 버전 이상(메이저가 같은 후보만 비교, `,;/|`로 여러 개 허용)
- 판정 규칙을 바꾸면 `backend/tests/test_osv.py`와 프론트 `utils/health.ts`의 표시 로직을 같이 확인한다.

## 5. 프론트

- `ProxyHealthPage`는 View by(Vulnerabilities 기본 / Licenses), 반입 상태 필터(`all | hosted | pending`), 정렬, 페이지(`HEALTH_PAGE_SIZE = 10`), `xlsx` 내보내기를 가진다.
- override 편집은 `VulnOverrideModal`, owner(`can_request`)에게만 노출한다.
- override 키는 `vulnOverrideKey(problemCode, artifact)`로 만든다.
- 해결 버전이 비어 있으면 `미해결`로 표시한다(`formatFixedVersions`).

## 6. 운영 스크립트

- `backend/scripts/refresh_osv_fixed_versions.py`: 잘못 저장된 `fixed_version`을 지우고 OSV 보강을 다시 돌린다. 스키마나 판정 규칙을 바꾸면 이 스크립트가 여전히 맞는지 확인한다.
