---
name: packages-web-package-request
description: packages-web 패키지 신청(GitOps PR) 흐름 표준 - 검증 체크, requests YAML 병합, 브랜치/PR 생성, auto-merge, 반영 상태 조회. Use when editing backend/app/services/gitops.py, backend/app/services/github.py, backend/app/routers/package_request.py, or frontend PackageRequestPage.
when_to_use: 패키지 신청 검증/신청/상태 API 수정 시. gitops.py, github.py 수정 시. requests/inventory YAML 형식 관련 작업 시. PackageRequestPage.tsx 수정 시. 신청 개수·중복 규칙 변경 시.
origin: packages-web
---

# packages-web Package Request (GitOps)

## 0. 흐름

```text
POST /api/request/{eco}/validate  -> gitops.validate_package_request (항목별 checks)
POST /api/request/{eco}           -> gitops.submit_package_request  (브랜치 + requests YAML + PR + auto-merge)
GET  /api/request/{eco}/{pr}?packages=name==ver,...  -> merge_if_ready + Hosted 반영 확인
```

- 모든 신청 API는 `require_cicd_owner`(CICD org owner)만 쓴다.
- GitOps 저장소: `settings.github_org`(기본 `CICD`) / `ECOSYSTEM_MAP[eco].gitops_repo`, 기준 브랜치 `settings.github_base_branch`.
- `settings.github_token`이 없으면 503.

## 1. 검증 체크 (`validate_package_request`)

각 체크는 `{"key", "label", "passed", "detail"}` dict이며 라우터에서 `PackageRequestCheck`로 바꾼다. 순서와 key를 유지한다.

| key | 통과 조건 | 근거 |
| --- | --- | --- |
| `upstream` | 공개 레지스트리/proxy에 버전 존재 | `nexus.upstream_version_exists` (예외는 실패 체크로 표시) |
| `hosted` | Hosted에 **없음** | `hosted_has_exact` |
| `inventory` | `inventory_file`에 **없음** | `_inventory_has` |
| `requests` | `requests_file`에 **없음** | `_requests_has` |
| `duplicate` | 요청 내 중복 없음 | 라우터에서 추가 |

- 새 체크를 추가하면 프론트 `PackageRequestPage.tsx`의 체크 표시와 `backend/tests/test_package_request.py`를 같이 수정한다.
- `label`/`detail`은 화면에 그대로 나오는 한국어 문장이다.

## 2. 요청 규칙

- 한 번에 최대 10개(`_normalize_packages`, `_parse_packages_query`). 초과 시 400 `"최대 10개까지 신청할 수 있습니다"`.
- 이름·버전은 `strip()` 후 필수. 중복 판정 키는 `(name.lower(), version)`.
- npm scoped 이름(`@scope/pkg`)을 지원한다. inventory 문자열 `name@version`은 `rpartition("@")`으로 나눈다.
- 제출 시 모든 항목을 다시 검증하고, 하나라도 실패하면 `RequestRejected` → 409.

## 3. YAML 형식

requests 파일:

```yaml
ecosystem: pypi
packages:
  - name: requests
    versions: ["2.32.3"]
```

- 병합은 `merge_request_package`(이름 대소문자 무시, 같은 버전 있으면 `RequestRejected`).
- 저장은 `yaml.safe_dump(doc, sort_keys=False, allow_unicode=True)`. 키 순서를 바꾸는 dump를 쓰지 않는다.
- inventory 파일은 dict 목록(`name` + `versions`/`version`)과 `name@version` 문자열을 모두 읽는다.

## 4. 브랜치 / PR

- 브랜치: `request/{YYYYMMDD}-web-{slug(첫 패키지)}`, 여러 개면 `-x{n}` 접미사.
- 커밋 메시지: `request: add name==ver, ... via packages-web`.
- PR 본문에 Ecosystem, 패키지 목록, `Requested-by: @login`을 넣는다.
- `settings.transfer_auto_merge`가 켜져 있으면 `github.enable_automerge(node_id)` 후 `merge_if_ready`. **필수 체크를 우회하는 강제 머지는 하지 않는다.**
- GitHub REST/GraphQL 호출은 `backend/app/services/github.py`에만 둔다. 실패는 `GitHubError(message, status_code=...)`.

## 5. 반영 상태 (`delivery`)

| 값 | 조건 |
| --- | --- |
| `pending` | PR 미머지 |
| `merged` | 머지됨, 조회할 패키지 목록 없음 |
| `delivering` | 머지됨, 일부가 아직 Hosted에 없음 |
| `done` | 모든 패키지가 Hosted에 있음 |

- 상태 조회는 CI가 통과했으면 `merge_if_ready`로 머지를 시도한다. 조회 API에 부작용이 있다는 점을 유지한다.
- 프론트는 이전 신청이 `done`이 될 때까지 추가 신청을 막는다(검증은 가능).
