# packages-web

Nexus **Hosted** 저장소에 패키지가 등록되어 있는지 확인하는 웹 도구입니다.

## 기능

- 포맷(pypi / npm / nuget) 선택 후 패키지 **이름**으로 Hosted 존재 여부 확인
- **버전**(선택) 지정 시 해당 버전의 정확 일치 여부 확인
- 이름 없이 버전만 입력하는 검색은 지원하지 않음

## 구조

```text
/backend   — FastAPI (Nexus Search API)
/frontend  — React + Vite + TypeScript
```

## 사전 요구사항

- [uv](https://docs.astral.sh/uv/) (Python 3.12+)
- Node.js 20+

## 실행

### Backend

```bash
cd backend
uv sync
uv run uvicorn main:app --reload --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

브라우저: `http://localhost:5173`

## API

### Hosted 존재 확인

```text
GET /api/packages/check?format=pypi&name=requests
GET /api/packages/check?format=pypi&name=requests&version=2.32.3
```

응답 예시:

```json
{
  "exists": true,
  "name": "requests",
  "format": "pypi",
  "repository": "pypi-hosted",
  "versions": ["2.32.3", "2.31.0"],
  "matched_version": null
}
```

## 환경변수

루트 `.env.example`을 `.env`로 복사한 뒤 값을 채웁니다.

| 변수 | 설명 |
| ---- | ---- |
| `NEXUS_BASE_URL` | Nexus 서버 URL |
| `NEXUS_USERNAME` / `NEXUS_PASSWORD` | Nexus 인증 |
| `NEXUS_VERIFY_SSL` | TLS 인증서 검증 여부 |
| `CORS_ORIGINS` | 허용할 프론트 오리진 (쉼표 구분) |

## 구현 단계

| 단계 | 내용 | 상태 |
| ---- | ---- | ---- |
| 1 | 뼈대 생성 | 완료 |
| 2 | Hosted 패키지 존재 확인 + UI | 완료 |
| 3~5 | 이관 등 추가 기능 | 추후 계획 |
