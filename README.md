# packages-web

Nexus Proxy 저장소의 패키지를 조회하고, 기존 `CICD/*Packages` 저장소의 GitOps 파이프라인을 통해 Hosted 저장소로 이관하는 웹 도구입니다.

## 구조

```text
/backend   — FastAPI (Nexus 조회 + GitOps 이관 오케스트레이션)
/frontend  — React + Vite + TypeScript (패키지 목록 UI)
```

## 사전 요구사항

- [uv](https://docs.astral.sh/uv/) (Python 3.12+)
- Node.js 24+

## 실행

### Backend

```bash
cd backend
uv sync
uv run uvicorn main:app --reload --port 8000
```

헬스체크: `GET http://localhost:8000/health` → `{"status":"ok"}`

### Frontend

```bash
cd frontend
npm install
npm run dev
```

브라우저: `http://localhost:5173`

## 환경변수

루트 `.env.example`을 `.env`로 복사한 뒤 값을 채웁니다.

| 변수 | 설명 |
| ---- | ---- |
| `NEXUS_BASE_URL` | Nexus 서버 URL |
| `NEXUS_USERNAME` / `NEXUS_PASSWORD` | Nexus 인증 |
| `GITHUB_API_BASE` | Enterprise GitHub API base (기본: `https://github.sk-inc.com/api/v3`) |
| `GITHUB_TOKEN` | GitHub PAT (contents:write, pull_requests:write) |
| `GITHUB_ORG` | 대상 org (기본: `CICD`) |
| `TRANSFER_AUTO_MERGE` | PR 생성 후 auto-merge 활성화 여부 |

## 구현 단계

| 단계 | 내용 | 상태 |
| ---- | ---- | ---- |
| 1 | 뼈대 생성 | 완료 |
| 2 | Nexus 패키지 검색 | 예정 |
| 3 | pypi 이관 (GitOps) | 예정 |
| 4 | npm 이관 | 예정 |
| 5 | nuget 이관 | 예정 |

## 이관 흐름 (3단계 이후)

1. UI에서 Proxy 패키지 선택 → [Hosted로 이관]
2. 백엔드가 대상 repo의 `requests/<eco>_requests_list.yaml`에 패키지 추가 PR 생성
3. CI 통과 후 auto-merge → 기존 `cd.yml` 실행 → Proxy에서 다운로드 → Hosted 업로드
