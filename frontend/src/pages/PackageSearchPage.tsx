import { useEffect, useState } from "react";
import { checkPackage } from "../api/client";
import ExistenceResult from "../components/ExistenceResult";
import SearchForm from "../components/SearchForm";
import type { PackageCheckResponse, PackageType } from "../types";

const STORAGE_KEY = "packages-web:package-search";
const PACKAGE_TYPES: PackageType[] = ["pypi", "npm", "nuget"];

interface StoredSearch {
  packageType: PackageType;
  name: string;
  version: string;
  queriedVersion: string;
  result: PackageCheckResponse | null;
  searched: boolean;
}

function normalizeResult(raw: unknown): PackageCheckResponse | null {
  if (!raw || typeof raw !== "object") return null;
  const r = raw as Partial<PackageCheckResponse>;
  if (typeof r.query !== "string" || typeof r.format !== "string") return null;
  if (!Array.isArray(r.packages)) return null;
  const packages = r.packages
    .filter(
      (p): p is { name: string; versions: string[] } =>
        !!p &&
        typeof p === "object" &&
        typeof (p as { name?: unknown }).name === "string" &&
        Array.isArray((p as { versions?: unknown }).versions),
    )
    .map((p) => ({
      name: p.name,
      versions: p.versions.map(String),
    }));
  return {
    exists: Boolean(r.exists ?? packages.length > 0),
    query: r.query,
    format: r.format,
    repository: typeof r.repository === "string" ? r.repository : "",
    packages,
    matched_version:
      typeof r.matched_version === "string" ? r.matched_version : null,
    continuation_token:
      typeof r.continuation_token === "string" ? r.continuation_token : null,
  };
}

function loadStored(): StoredSearch | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<StoredSearch>;
    const packageType = PACKAGE_TYPES.includes(parsed.packageType as PackageType)
      ? (parsed.packageType as PackageType)
      : "pypi";
    return {
      packageType,
      name: typeof parsed.name === "string" ? parsed.name : "",
      version: typeof parsed.version === "string" ? parsed.version : "",
      queriedVersion:
        typeof parsed.queriedVersion === "string" ? parsed.queriedVersion : "",
      result: normalizeResult(parsed.result),
      searched: Boolean(parsed.searched && parsed.result),
    };
  } catch {
    localStorage.removeItem(STORAGE_KEY);
    return null;
  }
}

function saveStored(state: StoredSearch) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
}

function mergeResults(
  prev: PackageCheckResponse,
  next: PackageCheckResponse,
): PackageCheckResponse {
  const map = new Map<string, Set<string>>();
  for (const pkg of prev.packages) {
    map.set(pkg.name, new Set(pkg.versions));
  }
  for (const pkg of next.packages) {
    const versions = map.get(pkg.name) ?? new Set();
    pkg.versions.forEach((v) => versions.add(v));
    map.set(pkg.name, versions);
  }

  const packages = [...map.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([name, versions]) => ({
      name,
      versions: [...versions].sort().reverse(),
    }));

  return {
    ...next,
    packages,
    exists: packages.length > 0,
  };
}

export default function PackageSearchPage() {
  const stored = loadStored();
  const [packageType, setPackageType] = useState<PackageType>(
    stored?.packageType ?? "pypi",
  );
  const [name, setName] = useState(stored?.name ?? "");
  const [version, setVersion] = useState(stored?.version ?? "");
  const [queriedVersion, setQueriedVersion] = useState(
    stored?.queriedVersion ?? "",
  );

  const [result, setResult] = useState<PackageCheckResponse | null>(
    stored?.result ?? null,
  );
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [searched, setSearched] = useState(stored?.searched ?? false);

  useEffect(() => {
    saveStored({
      packageType,
      name,
      version,
      queriedVersion,
      result,
      searched,
    });
  }, [packageType, name, version, queriedVersion, result, searched]);

  const runSearch = async (token?: string, append = false) => {
    const trimmedName = name.trim();
    if (!trimmedName) return;

    setLoading(true);
    setError(null);
    if (!append) {
      setSearched(true);
      setQueriedVersion(version.trim());
    }

    try {
      const data = await checkPackage({
        format: packageType,
        name: trimmedName,
        version: append ? queriedVersion || undefined : version.trim() || undefined,
        continuationToken: token,
      });
      setResult((prev) =>
        append && prev ? mergeResults(prev, data) : data,
      );
    } catch (err) {
      if (!append) setResult(null);
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  };

  return (
    <>
      <SearchForm
        packageType={packageType}
        name={name}
        version={version}
        loading={loading}
        onPackageTypeChange={setPackageType}
        onNameChange={setName}
        onVersionChange={setVersion}
        onSubmit={() => runSearch()}
      />
      <ExistenceResult
        result={result}
        queriedVersion={queriedVersion}
        loading={loading}
        error={error}
        searched={searched}
        onLoadMore={
          result?.continuation_token
            ? () => runSearch(result.continuation_token!, true)
            : undefined
        }
      />
    </>
  );
}
