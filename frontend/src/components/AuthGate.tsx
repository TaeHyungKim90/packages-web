import { Navigate, Outlet } from "react-router";
import type { useAuth } from "../hooks/useAuth";

type Auth = ReturnType<typeof useAuth>;

export function RequireAuth({ auth }: { auth: Auth }) {
  if (auth.isLoading) {
    return (
      <div className="auth-loading">
        <span className="spinner" aria-hidden="true" />
        인증 확인 중…
      </div>
    );
  }
  if (!auth.isAuthenticated) {
    return <Navigate to="/login" replace />;
  }
  return <Outlet />;
}

export function RedirectIfAuthed({ auth }: { auth: Auth }) {
  if (auth.isLoading) {
    return (
      <div className="auth-loading">
        <span className="spinner" aria-hidden="true" />
        인증 확인 중…
      </div>
    );
  }
  if (auth.isAuthenticated) {
    return <Navigate to="/search" replace />;
  }
  return <Outlet />;
}

export function RequireRequestAccess({ auth }: { auth: Auth }) {
  if (auth.isLoading) {
    return (
      <div className="auth-loading">
        <span className="spinner" aria-hidden="true" />
        인증 확인 중…
      </div>
    );
  }
  if (!auth.isAuthenticated) {
    return <Navigate to="/login" replace />;
  }
  if (!auth.user?.can_request) {
    return <Navigate to="/search" replace />;
  }
  return <Outlet />;
}

export function RequireOrgsAccess({ auth }: { auth: Auth }) {
  if (auth.isLoading) {
    return (
      <div className="auth-loading">
        <span className="spinner" aria-hidden="true" />
        인증 확인 중…
      </div>
    );
  }
  if (!auth.isAuthenticated) {
    return <Navigate to="/login" replace />;
  }
  if (!auth.user?.can_view_orgs) {
    return <Navigate to="/search" replace />;
  }
  return <Outlet />;
}

export function RootRedirect({ auth }: { auth: Auth }) {
  if (auth.isLoading) {
    return (
      <div className="auth-loading">
        <span className="spinner" aria-hidden="true" />
        인증 확인 중…
      </div>
    );
  }
  return <Navigate to={auth.isAuthenticated ? "/search" : "/login"} replace />;
}
