import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { fetchGhesOrgs, fetchProjectPackages, syncProjectPackages } from "../api/client";
import Pagination from "../components/Pagination";
import type { AggregatedPackageRow } from "../types";
import {
  DEFAULT_HEALTH_SORT,
  formatImportedAt,
  formatReportTime,
  matchesThreatBand,
  nextHealthSort,
  threatSeverity,
  type HealthSort,
  type HealthSortKey,
  type ThreatBand,
} from "../utils/health";
import { paginate } from "../utils/result";

const PAGE_SIZE = 20;

function SortHeader({
  label,
  column,
  sort,
  onSort,
}: {
  label: string;
  column: HealthSortKey;
  sort: HealthSort;
  onSort: (key: HealthSortKey) => void;
}) {
  const active = sort.key === column;
  const ariaSort = active
    ? sort.dir === "asc"
      ? "ascending"
      : "descending"
    : "none";
  return (
    <th aria-sort={ariaSort}>
      <button
        type="button"
        className={`sort-header${active ? " sort-header--active" : ""}`}
        onClick={() => onSort(column)}
      >
        {label}
        <span className="sort-header__mark" aria-hidden="true">
          {active ? (sort.dir === "asc" ? "▲" : "▼") : "↕"}
        </span>
      </button>
    </th>
  );
}

function sortRows(rows: AggregatedPackageRow[], sort: HealthSort): AggregatedPackageRow[] {
  const copy = [...rows];
  copy.sort((a, b) => {
    if (sort.key === "name") {
      const cmp = a.name.localeCompare(b.name, undefined, { sensitivity: "base" });
      return sort.dir === "asc" ? cmp : -cmp;
    }
    const left = a.max_threat_level;
    const right = b.max_threat_level;
    if (left == null && right == null) {
      return a.name.localeCompare(b.name, undefined, { sensitivity: "base" });
    }
    if (left == null) return 1;
    if (right == null) return -1;
    const cmp = left - right;
    return sort.dir === "asc" ? cmp : -cmp;
  });
  return copy;
}

export default function ProjectPackagesPage() {
  const [orgs, setOrgs] = useState<string[]>([]);
  const [org, setOrg] = useState("");
  const [name, setName] = useState("");
  const [format, setFormat] = useState("");
  const [threatBand, setThreatBand] = useState<ThreatBand>("all");
  const [appliedOrg, setAppliedOrg] = useState("");
  const [appliedName, setAppliedName] = useState("");
  const [appliedFormat, setAppliedFormat] = useState("");
  const [appliedThreatBand, setAppliedThreatBand] = useState<ThreatBand>("all");
  const [items, setItems] = useState<AggregatedPackageRow[]>([]);
  const [collectedAt, setCollectedAt] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [sort, setSort] = useState<HealthSort>(DEFAULT_HEALTH_SORT);
  const [page, setPage] = useState(1);

  const loadOrgs = useCallback(async () => {
    const data = await fetchGhesOrgs();
    setOrgs(data.organizations.filter((o) => o.managed).map((o) => o.name));
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchProjectPackages({
        org: appliedOrg || undefined,
        name: appliedName || undefined,
        format: appliedFormat || undefined,
      });
      setItems(data.items);
      setCollectedAt(data.collected_at);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [appliedOrg, appliedName, appliedFormat]);

  useEffect(() => {
    void loadOrgs().catch((err) =>
      setError(err instanceof Error ? err.message : String(err)),
    );
  }, [loadOrgs]);

  useEffect(() => {
    void load();
  }, [load]);

  const filtered = useMemo(
    () =>
      items.filter((row) =>
        matchesThreatBand(row.max_threat_level, appliedThreatBand),
      ),
    [items, appliedThreatBand],
  );
  const sorted = useMemo(() => sortRows(filtered, sort), [filtered, sort]);
  const paged = useMemo(
    () => paginate(sorted, page, PAGE_SIZE),
    [sorted, page],
  );

  const handleSearch = (event: FormEvent) => {
    event.preventDefault();
    setPage(1);
    setAppliedOrg(org);
    setAppliedName(name.trim());
    setAppliedFormat(format);
    setAppliedThreatBand(threatBand);
    setMessage(null);
  };

  const handleSync = async () => {
    setSyncing(true);
    setError(null);
    setMessage(null);
    try {
      const result = await syncProjectPackages(org || undefined);
      setCollectedAt(result.collected_at);
      setMessage(`동기화 완료 (${result.item_count}개)`);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSyncing(false);
    }
  };

  return (
    <section className="card orgs-page proj-pkg-page">
      <div className="orgs-page__header">
        <h2 className="card__title">과제별 패키지</h2>
        <div className="orgs-page__actions">
          <button
            type="button"
            className="btn-primary"
            onClick={() => void handleSync()}
            disabled={loading || syncing}
          >
            {syncing ? "동기화 중…" : "동기화"}
          </button>
        </div>
      </div>
      <p className="orgs-page__hint">
        managed 과제의 lock 파일에서 패키지를 모읍니다. 여러 과제에서 쓰면 과제명은 쉼표로
        표시됩니다. 마지막 수집: {formatReportTime(collectedAt) || "-"}
      </p>

      <form className="proj-pkg__search" onSubmit={handleSearch}>
        <label>
          과제명
          <select value={org} onChange={(e) => setOrg(e.target.value)}>
            <option value="">전체</option>
            {orgs.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </select>
        </label>
        <label>
          패키지
          <select value={format} onChange={(e) => setFormat(e.target.value)}>
            <option value="">전체</option>
            <option value="pypi">pypi</option>
            <option value="npm">npm</option>
            <option value="nuget">nuget</option>
          </select>
        </label>
        <label>
          패키지 이름
          <input
            type="search"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="부분 일치"
          />
        </label>
        <label>
          위험도
          <select
            value={threatBand}
            onChange={(e) => setThreatBand(e.target.value as ThreatBand)}
          >
            <option value="all">전체</option>
            <option value="critical">Critical (7-10)</option>
            <option value="severe">Severe (4-6)</option>
            <option value="moderate">Moderate (1-3)</option>
          </select>
        </label>
        <button type="submit" className="btn-secondary" disabled={loading}>
          검색
        </button>
      </form>

      {error && <p className="orgs-page__error">{error}</p>}
      {message && <p className="orgs-page__ok">{message}</p>}
      {loading && (
        <p className="orgs-page__status">
          <span className="spinner" aria-hidden="true" />
          불러오는 중…
        </p>
      )}

      {!loading && (
        <>
          <table className="health-table">
            <thead>
              <tr>
                <SortHeader
                  label="패키지"
                  column="name"
                  sort={sort}
                  onSort={(key) => {
                    setSort((current) => nextHealthSort(current, key));
                    setPage(1);
                  }}
                />
                <th>버전</th>
                <th>반입날짜</th>
                <SortHeader
                  label="CVE 점수"
                  column="threat"
                  sort={sort}
                  onSort={(key) => {
                    setSort((current) => nextHealthSort(current, key));
                    setPage(1);
                  }}
                />
                <th>과제명</th>
              </tr>
            </thead>
            <tbody>
              {paged.pageItems.length === 0 && (
                <tr>
                  <td colSpan={5}>결과가 없습니다. 동기화를 실행해 보세요.</td>
                </tr>
              )}
              {paged.pageItems.map((row) => {
                const severity = threatSeverity(row.max_threat_level);
                return (
                  <tr key={`${row.format}:${row.name}:${row.version}`}>
                    <td>
                      <span className="proj-pkg__fmt">{row.format}</span> {row.name}
                    </td>
                    <td>{row.version}</td>
                    <td>{formatImportedAt(row.imported_at) || "-"}</td>
                    <td>
                      {row.max_threat_level == null ? (
                        "-"
                      ) : (
                        <span className={`threat threat--${severity}`}>
                          {row.max_threat_level.toFixed(1)}
                        </span>
                      )}
                    </td>
                    <td>{row.organizations.join(", ")}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <Pagination
            currentPage={paged.currentPage}
            totalPages={paged.totalPages}
            totalItems={sorted.length}
            pageSize={PAGE_SIZE}
            onPageChange={setPage}
          />
        </>
      )}
    </section>
  );
}
