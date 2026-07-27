import { useCallback, useEffect, useState } from "react";
import { fetchMe, logout as apiLogout } from "../api/client";
import type { AuthUser } from "../types";

type AuthStatus = "loading" | "authenticated" | "anonymous";

export function useAuth() {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [status, setStatus] = useState<AuthStatus>("loading");

  const refresh = useCallback(async () => {
    try {
      const me = await fetchMe();
      setUser(me);
      setStatus("authenticated");
    } catch {
      setUser(null);
      setStatus("anonymous");
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const logout = useCallback(async () => {
    try {
      await apiLogout();
    } finally {
      setUser(null);
      setStatus("anonymous");
    }
  }, []);

  return {
    user,
    status,
    isLoading: status === "loading",
    isAuthenticated: status === "authenticated",
    refresh,
    logout,
  };
}
