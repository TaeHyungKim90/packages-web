import type { ReactNode } from "react";
import { useLocation, useNavigate } from "react-router";
import type { useAuth } from "../hooks/useAuth";
import Header from "./Header";

interface Props {
  health: "ok" | "error" | "loading";
  auth: ReturnType<typeof useAuth>;
  children: ReactNode;
}

export default function Layout({ health, auth, children }: Props) {
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const isLogin = pathname === "/login";

  const dotClass =
    health === "ok"
      ? "status-dot status-dot--ok"
      : health === "error"
        ? "status-dot status-dot--error"
        : "status-dot status-dot--loading";

  const statusLabel =
    health === "ok" ? "API 연결됨" : health === "error" ? "API 오류" : "연결 확인 중";

  const handleLogout = async () => {
    await auth.logout();
    navigate("/login", { replace: true });
  };

  return (
    <div className="layout">
      <div className="layout__accent" aria-hidden="true" />
      <header className="layout__header">
        <div className="layout__header-top">
          <div className="layout__brand">
            <h1>Nexus Packages</h1>
          </div>
          <div className="layout__header-right">
            {auth.isAuthenticated && auth.user && (
              <div className="layout__user">
                {auth.user.avatar_url ? (
                  <img
                    className="layout__avatar"
                    src={auth.user.avatar_url}
                    alt=""
                    width={28}
                    height={28}
                  />
                ) : null}
                <span className="layout__login">{auth.user.login}</span>
                <button
                  type="button"
                  className="btn-logout"
                  onClick={() => void handleLogout()}
                >
                  로그아웃
                </button>
              </div>
            )}
            <div className="layout__status" title={statusLabel}>
              <span className={dotClass} aria-hidden="true" />
              <span>{statusLabel}</span>
            </div>
          </div>
        </div>
        {!isLogin && auth.isAuthenticated && (
          <Header canRequest={Boolean(auth.user?.can_request)} />
        )}
      </header>
      <main className="layout__main">{children}</main>
    </div>
  );
}
