import { useEffect } from "react";
import { useLocation } from "react-router";

/** Match backend PROXY_HEALTH_TTL_SECONDS default (2h). */
export const IDLE_RELOAD_MS = 2 * 60 * 60 * 1000;

/**
 * After `timeoutMs` with no user activity, reload the page.
 * Pointer/key activity and route changes reset the timer.
 */
export function useIdleReload(enabled: boolean, timeoutMs = IDLE_RELOAD_MS): void {
  const { pathname } = useLocation();

  useEffect(() => {
    if (!enabled || timeoutMs <= 0) return;

    let timer: ReturnType<typeof setTimeout> | undefined;

    const schedule = () => {
      if (timer !== undefined) clearTimeout(timer);
      timer = setTimeout(() => {
        window.location.reload();
      }, timeoutMs);
    };

    const onActivity = () => {
      schedule();
    };

    schedule();
    window.addEventListener("pointerdown", onActivity);
    window.addEventListener("keydown", onActivity);
    document.addEventListener("visibilitychange", onActivity);

    return () => {
      if (timer !== undefined) clearTimeout(timer);
      window.removeEventListener("pointerdown", onActivity);
      window.removeEventListener("keydown", onActivity);
      document.removeEventListener("visibilitychange", onActivity);
    };
  }, [enabled, timeoutMs, pathname]);
}
