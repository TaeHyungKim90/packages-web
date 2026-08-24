import type {
  AuthUser,
  CheckParams,
  GhesOrgItem,
  GhesOrgsResponse,
  PackageCheckResponse,
  PackageRequestResult,
  PackageRequestStatus,
  PackageRequestValidation,
  PackageType,
  ProxyHealthResponse,
} from "../types";

/** Empty = same-origin via Vite proxy (required for session cookie). */
const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "";

type RequestEco = PackageType;

async function apiFetch(path: string, init?: RequestInit): Promise<Response> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      ...init,
      credentials: "include",
      redirect: "manual",
    });
  } catch {
    redirectToLogin();
    throw new Error("unauthorized");
  }
  if (isLoginRedirect(res)) {
    redirectToLogin();
    throw new Error("unauthorized");
  }
  return res;
}

function isLoginRedirect(res: Response): boolean {
  if (res.type === "opaqueredirect") return true;
  return [301, 302, 303, 307, 308, 401].includes(res.status);
}

function redirectToLogin(): void {
  if (typeof window === "undefined") return;
  if (window.location.pathname === "/login") return;
  window.location.assign("/login");
}

export async function checkHealth(): Promise<{ status: string }> {
  const res = await apiFetch("/health");
  if (!res.ok) throw new Error(`Health check failed: ${res.status}`);
  return res.json();
}

export async function fetchMe(): Promise<AuthUser> {
  const res = await apiFetch("/api/auth/me");
  if (!res.ok) {
    throw new Error(res.status === 401 ? "unauthorized" : `auth/me failed: ${res.status}`);
  }
  return res.json();
}

export async function logout(): Promise<void> {
  const res = await apiFetch("/api/auth/logout", { method: "POST" });
  if (!res.ok) throw new Error(`logout failed: ${res.status}`);
}

export function getLoginUrl(): string {
  return `${API_BASE}/api/auth/login`;
}

export async function checkPackage(params: CheckParams): Promise<PackageCheckResponse> {
  const search = new URLSearchParams();
  search.set("format", params.format);
  search.set("name", params.name);
  if (params.version?.trim()) {
    search.set("version", params.version.trim());
  }
  if (params.continuationToken) {
    search.set("continuationToken", params.continuationToken);
  }

  const res = await apiFetch(`/api/packages/check?${search}`);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    const detail = body.detail ?? res.statusText;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return res.json();
}

function packagesPayload(packages: { name: string; version: string }[]) {
  return {
    packages: packages.map((p) => ({
      name: p.name.trim(),
      version: p.version.trim(),
    })),
  };
}

async function readError(res: Response): Promise<string> {
  const body = await res.json().catch(() => ({}));
  const detail = body.detail ?? res.statusText;
  return typeof detail === "string" ? detail : JSON.stringify(detail);
}

export async function validatePackageRequest(
  eco: RequestEco,
  params: { packages: { name: string; version: string }[] },
): Promise<PackageRequestValidation> {
  const res = await apiFetch(`/api/request/${eco}/validate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(packagesPayload(params.packages)),
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function requestPackage(
  eco: RequestEco,
  params: { packages: { name: string; version: string }[] },
): Promise<PackageRequestResult> {
  const res = await apiFetch(`/api/request/${eco}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(packagesPayload(params.packages)),
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function fetchRequestStatus(
  eco: RequestEco,
  prNumber: number,
  packages: { name: string; version: string }[] = [],
): Promise<PackageRequestStatus> {
  const search = new URLSearchParams();
  if (packages.length > 0) {
    // encodeURIComponent via URLSearchParams — needed for scoped npm (@scope/pkg)
    search.set(
      "packages",
      packages.map((p) => `${p.name.trim()}==${p.version.trim()}`).join(","),
    );
  }
  const qs = search.toString();
  const res = await apiFetch(
    `/api/request/${eco}/${prNumber}${qs ? `?${qs}` : ""}`,
  );
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function fetchProxyHealth(
  eco: RequestEco,
): Promise<ProxyHealthResponse> {
  const res = await apiFetch(`/api/proxy-health/${eco}`);
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function fetchGhesOrgs(): Promise<GhesOrgsResponse> {
  const res = await apiFetch("/api/ghes-orgs");
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function saveGhesOrgs(
  organizations: GhesOrgItem[],
): Promise<GhesOrgsResponse> {
  const res = await apiFetch("/api/ghes-orgs", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      organizations: organizations.map((o) => ({
        name: o.name,
        managed: o.managed,
        repos: o.repos.map((r) => ({
          name: r.name,
          managed: r.managed,
        })),
      })),
    }),
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

/** @deprecated Prefer validatePackageRequest("pypi", …) */
export async function validatePypiPackage(params: {
  packages: { name: string; version: string }[];
}): Promise<PackageRequestValidation> {
  return validatePackageRequest("pypi", params);
}

/** @deprecated Prefer fetchRequestStatus("pypi", …) */
export async function fetchPypiRequestStatus(
  prNumber: number,
  packages: { name: string; version: string }[] = [],
): Promise<PackageRequestStatus> {
  return fetchRequestStatus("pypi", prNumber, packages);
}

/** @deprecated Prefer requestPackage("pypi", …) */
export async function requestPypiPackage(params: {
  packages: { name: string; version: string }[];
}): Promise<PackageRequestResult> {
  return requestPackage("pypi", params);
}
