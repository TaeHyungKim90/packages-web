import { useState } from "react";
import { checkPackage } from "../api/client";
import ExistenceResult from "../components/ExistenceResult";
import SearchForm from "../components/SearchForm";
import type { PackageCheckResponse, PackageType } from "../types";

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
  const [packageType, setPackageType] = useState<PackageType>("pypi");
  const [name, setName] = useState("");
  const [version, setVersion] = useState("");
  const [queriedVersion, setQueriedVersion] = useState("");

  const [result, setResult] = useState<PackageCheckResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [searched, setSearched] = useState(false);

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
