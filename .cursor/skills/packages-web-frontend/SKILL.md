---
name: packages-web-frontend
description: packages-web 프론트엔드(React 19 + TypeScript + Vite + react-router v8) 구조와 작성 표준 - 라우트/메뉴 연결, api/client.ts 단일 API 계층, types.ts 동기화, 상태 관리, CSS 토큰, 엑셀 내보내기. Use when adding or editing pages, components, hooks, utils, routes, menu items, or styles under frontend/src.
when_to_use: frontend/src/pages/**, components/**, hooks/**, utils/** 신규/수정 시. App.tsx 라우트 추가 시. Header.tsx 메뉴 수정 시. api/client.ts, types.ts 수정 시. styles/tokens.css, global.css 수정 시.
origin: packages-web
---

# packages-web Frontend

## 0. 구조

```text
frontend/src/
├─ App.tsx          # 라우트 + 권한 게이트
├─ main.tsx
├─ api/client.ts    # 모든 백엔드 호출
├─ types.ts         # 백엔드 schemas.py 대응 타입
├─ pages/           # 라우트 단위 화면 (*Page.tsx, default export)
├─ components/      # Layout, Header, AuthGate, Pagination, SearchForm, 모달 등
├─ hooks/           # useAuth, useAppHealth, useIdleReload
├─ utils/           # 순수 함수 (health.ts, result.ts, highlight.tsx) + *.test.ts
└─ styles/          # tokens.css, global.css
```

- 상태 관리·데이터 페칭 라이브러리(TanStack Query, Zustand 등)와 UI 라이브러리, CSS 프레임워크를 도입하지 않는다. `useState` / `useEffect` / `useMemo` / `useCallback`과 일반 CSS 클래스로 작성한다.
- 라우팅은 `react-router`(v8)의 `Routes`, `Route`, `NavLink`, `Navigate`, `Outlet`을 쓴다.

## 1. 새 화면 추가

1. `pages/<Name>Page.tsx` 작성(default export). eco별 화면은 `packageType` prop으로 재사용한다(`ProxyHealthPage`, `PackageRequestPage`).
2. `App.tsx`에서 알맞은 게이트(`RequireAuth` / `RequireRequestAccess` / `RequireOrgsAccess`) 아래에 `Route` 추가.
3. `components/Header.tsx` 메뉴에 연결한다. 권한 메뉴는 `canRequest` / `canViewOrgs`로 감싼다. 드롭다운 active 판정(`pathname.startsWith(...)`)도 갱신한다.
4. 메뉴에서 닿지 않는 화면은 만들지 않는다.
5. 게이트와 메뉴 노출이 백엔드 권한 의존성과 같은지 확인한다(`packages-web-ghes-auth`).

## 2. API 호출

- 컴포넌트에서 `fetch`를 직접 쓰지 않는다. `api/client.ts`에 함수를 추가하고 `apiFetch`를 거친다(`credentials: "include"`, 401/3xx 시 `/login`).
- 실패는 `if (!res.ok) throw new Error(await readError(res))` — 백엔드 `detail` 문자열을 그대로 에러 메시지로 쓴다.
- 쿼리스트링은 `URLSearchParams`로 만든다(npm scoped 이름 `@scope/pkg` 인코딩).
- eco별 함수는 `(eco: RequestEco, ...)` 시그니처를 쓴다. `*Pypi*` 함수는 deprecated라 새로 쓰지 않는다.
- 백엔드 스키마를 바꾸면 `types.ts`를 같은 커밋에서 수정한다. 필드는 snake_case 그대로.

## 3. 화면 패턴

- 로딩/오류/메시지 상태를 `loading`, `error`, `message` state로 두고, 동기화 같은 긴 작업은 별도 `syncing` state로 버튼을 막는다.
- 목록 필터는 입력값과 적용값(`applied*`)을 분리하고 제출 시 적용한다. 파생 목록은 `useMemo`로 필터 → 정렬 → `paginate`.
- 정렬 헤더는 `aria-sort`와 `sort-header` 클래스 패턴을 따른다(`ProjectPackagesPage`의 `SortHeader`).
- 페이지는 `components/Pagination` + `utils/result.ts`의 `paginate`.
- 엑셀 내보내기는 `xlsx`(`import * as XLSX from "xlsx"`), 파일명 `<화면>-<eco/view>-<stamp>.xlsx`.
- 로그인 사용자는 `Layout`의 `useIdleReload`로 2시간 무활동 시 새로고침된다.
- 화면 문구는 한국어.

## 4. 스타일

- 색·간격·그림자·반경은 `styles/tokens.css`의 CSS 변수(`--sk-red`, `--surface`, `--border`, `--danger`, `--radius`, `--shadow` 등)를 쓴다. 새 hex 값을 컴포넌트 CSS에 직접 쓰지 않는다.
- 클래스는 BEM 형태(`header-nav__link--active`)를 따른다. 공통 스타일은 `styles/global.css`.
- 폰트는 `--font`(Pretendard).

## 5. 검증

- `make lint`(eslint + `tsc --noEmit`), `make type-check`, `make test`(vitest).
- 로직이 들어가는 순수 함수는 `utils/`로 빼고 `*.test.ts`를 추가한다.
- 개발 서버는 `make frontend`(5173), 백엔드와 같이 띄울 때는 `make dev`. `VITE_API_BASE_URL`은 비워 두고 Vite proxy를 쓴다.
