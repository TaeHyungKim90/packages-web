import type {
  AuthUser,
  CheckParams,
  PackageCheckResponse,
  PackageRequestResult,
  PackageRequestStatus,
  PackageRequestValidation,
} from "../types";

/** Empty = same-origin via Vite proxy (required for session cookie). */
const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "";

async function apiFetch(path: string, init?: RequestInit): Promise<Response> {
  return fetch(`${API_BASE}${path}`, {
    ...init,
    credentials: "include",
  });
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

export async function validatePypiPackage(params: {
  packages: { name: string; version: string }[];
}): Promise<PackageRequestValidation> {
  const res = await apiFetch("/api/request/pypi/validate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      packages: params.packages.map((p) => ({
        name: p.name.trim(),
        version: p.version.trim(),
      })),
    }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    const detail = body.detail ?? res.statusText;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return res.json();
}

export async function fetchPypiRequestStatus(
  prNumber: number,
  packages: { name: string; version: string }[] = [],
): Promise<PackageRequestStatus> {
  const search = new URLSearchParams();
  if (packages.length > 0) {
    search.set(
      "packages",
      packages.map((p) => `${p.name.trim()}==${p.version.trim()}`).join(","),
    );
  }
  const qs = search.toString();
  const res = await apiFetch(
    `/api/request/pypi/${prNumber}${qs ? `?${qs}` : ""}`,
  );
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    const detail = body.detail ?? res.statusText;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return res.json();
}

export async function requestPypiPackage(params: {
  packages: { name: string; version: string }[];
}): Promise<PackageRequestResult> {
  const res = await apiFetch("/api/request/pypi", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      packages: params.packages.map((p) => ({
        name: p.name.trim(),
        version: p.version.trim(),
      })),
    }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    const detail = body.detail ?? res.statusText;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return res.json();
}
