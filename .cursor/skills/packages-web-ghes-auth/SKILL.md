---
name: packages-web-ghes-auth
description: packages-web GHES OAuth 로그인, 서명 세션 쿠키, 권한 게이트(require_user / require_cicd_owner / require_sk_inc)와 프론트 AuthGate 연동 표준. Use when editing login/logout/me, session handling, permission checks, or route guards and menu visibility in the frontend.
when_to_use: backend/app/routers/auth.py, backend/app/deps.py, backend/app/services/session.py, backend/app/services/ghes_oauth.py 수정 시. frontend/src/components/AuthGate.tsx, frontend/src/hooks/useAuth.ts, Header.tsx 메뉴 노출 수정 시. 새 권한 등급 추가 시.
origin: packages-web
---

# packages-web GHES Auth

## 1. 로그인 흐름

```text
GET /api/auth/login     -> sign_oauth_state(nonce) -> GHES authorize URL로 302
GET /api/auth/callback  -> verify_oauth_state(max_age=600) -> 토큰 교환 -> 사용자 조회
                        -> set_session_cookie -> {frontend}/search 로 302
POST /api/auth/logout   -> clear_session_cookie
GET /api/auth/me        -> UserResponse(login, name, avatar_url, can_request, can_view_orgs)
```

- 콜백 실패는 예외를 올리지 않고 `_frontend_login(error)`로 `/login?error=...` 리다이렉트한다.
- OAuth 설정(`GITHUB_OAUTH_CLIENT_ID/SECRET`)이 없으면 로그인 화면에 오류를 보여준다.
- GHES access token은 세션에 저장하지 않는다. 서버 측 GitHub 호출은 `settings.github_token`을 쓴다.

## 2. 세션 (`services/session.py`, `deps.py`)

- `itsdangerous.URLSafeTimedSerializer(settings.session_secret, salt=...)`. salt는 `oauth-state`, `session-user`로 분리한다.
- 페이로드는 `SessionUser(login, name, avatar_url)`만. 권한 플래그를 쿠키에 넣지 않는다(매 요청 계산).
- 쿠키: `settings.session_cookie_name`, `httponly=True`, `samesite="lax"`, `secure=settings.session_cookie_secure`, `path="/"`, `max_age=session_max_age_seconds`.
- 만료·위조는 `load_session`이 `ValueError` → `require_user`가 401.

## 3. 권한 등급

| 등급 | 백엔드 | `/auth/me` 플래그 | 프론트 게이트 | 메뉴 |
| --- | --- | --- | --- | --- |
| 로그인 | `require_user` | - | `RequireAuth` | 패키지검색, 패키지 보안 취약점 |
| CICD owner | `require_cicd_owner` (`github.is_org_owner`) | `can_request` | `RequireRequestAccess` | 패키지신청 |
| sk-inc 관리 | `require_sk_inc` (`can_view_orgs`, `settings.ghes_inventory_login`) | `can_view_orgs` | `RequireOrgsAccess` | 관리(GHES 조직, GHES 가입자, 과제별 패키지) |

- 새 권한 등급이나 판정 변경은 **네 곳을 함께** 수정한다: `deps.py`의 의존성, `/auth/me` 플래그, `AuthGate.tsx`의 게이트 컴포넌트, `Header.tsx` 메뉴 노출.
- 같은 화면 안에서 등급에 따라 동작이 갈리는 경우(예: 취약점 조회에서 owner만 live 새로고침, 일반 사용자는 DB 스냅샷)는 라우터 안에서 `github.is_org_owner(user.login)`로 분기한다.
- 로그인 비교는 `strip().lower()`로 한다.

## 4. 프론트 규칙

- 모든 API 호출은 `frontend/src/api/client.ts`의 `apiFetch`를 거친다: `credentials: "include"`, `redirect: "manual"`.
- 401, 3xx, `opaqueredirect` 응답은 `/login`으로 보낸다. 백엔드는 외부 시스템 인증 실패를 401로 돌려주면 안 된다(502로 매핑).
- 게이트 컴포넌트는 `auth.isLoading` 동안 스피너(`인증 확인 중…`)를 보여주고, 권한이 없으면 `/search`로 `Navigate replace`.
- `VITE_API_BASE_URL`은 비워 둔다(같은 출처 + Vite proxy여야 세션 쿠키가 붙는다).

## 5. 테스트

- 세션 쿠키가 필요한 API 테스트는 `set_session_cookie`로 만든 값을 `TestClient.cookies`에 넣는다(`test_project_packages_api.py`의 `_authed()` 참조).
- 권한별 401(쿠키 없음) / 403(다른 계정) / 200 세 케이스를 둔다. `is_org_owner`는 monkeypatch한다.
