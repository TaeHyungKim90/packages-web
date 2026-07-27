# packages-web

Nexus **Hosted** 저장소 패키지 검색과 PyPI 패키지 신청(GitOps PR)을 제공하는 웹 도구입니다.

GHES(GitHub Enterprise) 계정으로 로그인한 뒤 사용할 수 있습니다.

## 기능

### 패키지 검색

- 포맷(pypi / npm / nuget) 선택 후 패키지 **이름**으로 Hosted 존재 여부 확인
- **버전**(선택) 지정 시 해당 버전의 정확 일치·부분 일치 검색
- 이름 없이 버전만 입력하는 검색은 지원하지 않음

### PyPI 패키지 신청

- 신청 전 **검증**: 업스트림 버전 존재, Hosted·inventory·요청 목록 중복 확인
- 한 번에 최대 **10개** 패키지를 한 PR로 신청 (`+` / `−` 행 추가·삭제)
- 신청 후 진행 상태를 화면에 표시
  - 검사 중 → 받는 중 → Hosted 등록 완료
- 이전 신청이 완료될 때까지 추가 신청 불가 (검증은 가능)
- 10개를 넘는 다량 신청은 담당자에게 메일로 목록을 보내 등록 요청

> npm / NuGet 신청 UI는 준비 중입니다.

## 구조

```text
/backend   — FastAPI (Nexus · GHES OAuth · GitOps)
/frontend  — React + Vite + TypeScript
```

## 사전 요구사항

- [uv](https://docs.astral.sh/uv/) (Python 3.12+)
- Node.js 20+

## 실행

루트 `.env.example`을 `.env`로 복사한 뒤 값을 채웁니다.

```bash
make env
make install
make dev          # backend :8000 + frontend :5173
```

또는 개별 실행:

```bash
make backend      # FastAPI (port 8000)
make frontend     # Vite (port 5173)
```

브라우저: `http://localhost:5173`

### 기타 Make 타깃

| 명령 | 설명 |
| ---- | ---- |
| `make lint` / `make test` / `make check` | 린트 · 테스트 · 둘 다 |
| `make build` | 프론트 프로덕션 빌드 |

## API

인증이 필요한 엔드포인트는 GHES OAuth 세션 쿠키가 필요합니다.

### Hosted 존재 확인

```text
GET /api/packages/check?format=pypi&name=requests
GET /api/packages/check?format=pypi&name=requests&version=2.32.3
```

### PyPI 신청 검증 / 신청 / 상태

```text
POST /api/request/pypi/validate
POST /api/request/pypi
GET  /api/request/pypi/{pr_number}?packages=name==ver[,name2==ver2]
```

요청 본문 예시 (`validate` / `pypi`):

```json
{
  "packages": [
    { "name": "requests", "version": "2.32.3" },
    { "name": "httpx", "version": "0.27.0" }
  ]
}
```

상태 응답의 `delivery` 값:

| 값 | 의미 |
| ---- | ---- |
| `pending` | PR 미머지 (검사 중) |
| `merged` / `delivering` | 머지됨, Hosted 반영 대기 |
| `done` | Hosted에 모두 등록됨 |

## 환경변수

루트 `.env.example`을 `.env`로 복사한 뒤 값을 채웁니다.

| 변수 | 설명 |
| ---- | ---- |
| `NEXUS_BASE_URL` | Nexus 서버 URL |
| `NEXUS_USERNAME` / `NEXUS_PASSWORD` | Nexus 인증 |
| `NEXUS_VERIFY_SSL` | TLS 인증서 검증 여부 |
| `PYPI_JSON_BASE_URL` | PyPI JSON API 베이스 (업스트림 버전 확인) |
| `NPM_REGISTRY_BASE_URL` | npm registry 베이스 |
| `CORS_ORIGINS` | 허용할 프론트 오리진 (쉼표 구분) |
| `GITHUB_BASE_URL` / `GITHUB_API_BASE` | GHES URL |
| `GITHUB_OAUTH_CLIENT_ID` / `GITHUB_OAUTH_CLIENT_SECRET` | OAuth 앱 |
| `OAUTH_REDIRECT_URI` / `FRONTEND_BASE_URL` | 콜백·프론트 URL |
| `SESSION_SECRET` 등 | 세션 쿠키 설정 |
| `GITHUB_TOKEN` / `GITHUB_ORG` / `GITHUB_BASE_BRANCH` | GitOps 봇 PAT·조직 |
| `TRANSFER_AUTO_MERGE` | CI 통과 후 auto-merge 사용 여부 |

## 구현 단계

| 단계 | 내용 | 상태 |
| ---- | ---- | ---- |
| 1 | 뼈대 생성 | 완료 |
| 2 | Hosted 패키지 검색 + UI | 완료 |
| 3 | GHES OAuth 로그인 | 완료 |
| 4 | PyPI 패키지 신청 (검증 · 다중 신청 · 진행 상태) | 완료 |
| 5 | npm / NuGet 신청 | 추후 계획 |
