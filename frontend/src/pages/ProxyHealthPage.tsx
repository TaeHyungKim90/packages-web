import { useEffect, useMemo, useState } from "react";
import * as XLSX from "xlsx";
import { fetchProxyHealth } from "../api/client";
import Pagination from "../components/Pagination";
import type {
  PackageType,
  ProxyHealthResponse,
  ProxyHealthView,
} from "../types";
import {
  HEALTH_PAGE_SIZE,
  DEFAULT_HEALTH_SORT,
  aggregateLicenses,
  aggregateVulnerabilities,
  filterLicenses,
  filterVulnerabilities,
  filterVulnerabilitiesByBand,
  formatImportedAt,
  formatReportTime,
  formatThreatInteger,
  licenseThreatClass,
  licenseThreatLabel,
  nextHealthSort,
  sortAggregatedLicenses,
  sortAggregatedVulnerabilities,
  threatSeverity,
  type HealthSort,
  type HealthSortKey,
  type ThreatBand,
} from "../utils/health";
import { paginate } from "../utils/result";

const LABEL_MAP: Record<PackageType, string> = {
  pypi: "PyPI",
  npm: "npm",
  nuget: "NuGet",
};

interface Props {
  packageType: PackageType;
}

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

export default function ProxyHealthPage({ packageType }: Props) {
  const [data, setData] = useState<ProxyHealthResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<ProxyHealthView>("vulnerabilities");
  const [query, setQuery] = useState("");
  const [threatBand, setThreatBand] = useState<ThreatBand>("all");
  const [sort, setSort] = useState<HealthSort>(DEFAULT_HEALTH_SORT);
  const [page, setPage] = useState(1);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setData(null);
    setQuery("");
    setPage(1);
    setView("vulnerabilities");
    setThreatBand("all");
    setSort(DEFAULT_HEALTH_SORT);

    fetchProxyHealth(packageType)
      .then((result) => {
        if (!cancelled) setData(result);
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : String(err));
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [packageType]);

  const vulnAllRows = useMemo(
    () => aggregateVulnerabilities(data?.vulnerabilities ?? []),
    [data],
  );
  const licenseAllRows = useMemo(
    () => aggregateLicenses(data?.licenses ?? []),
    [data],
  );
  const vulnRows = useMemo(() => {
    const aggregated = query.trim()
      ? aggregateVulnerabilities(
          filterVulnerabilities(data?.vulnerabilities ?? [], query),
        )
      : vulnAllRows;
    return filterVulnerabilitiesByBand(aggregated, threatBand);
  }, [data, query, threatBand, vulnAllRows]);
  const sortedVulnRows = useMemo(
    () => sortAggregatedVulnerabilities(vulnRows, sort),
    [vulnRows, sort],
  );
  const licenseRows = useMemo(
    () =>
      query.trim()
        ? aggregateLicenses(filterLicenses(data?.licenses ?? [], query))
        : licenseAllRows,
    [data, query, licenseAllRows],
  );
  const sortedLicenseRows = useMemo(
    () => sortAggregatedLicenses(licenseRows, sort),
    [licenseRows, sort],
  );
  const activeCount =
    view === "vulnerabilities" ? sortedVulnRows.length : sortedLicenseRows.length;
  const vulnPage = paginate(sortedVulnRows, page, HEALTH_PAGE_SIZE);
  const licensePage = paginate(sortedLicenseRows, page, HEALTH_PAGE_SIZE);
  const totalPages =
    view === "vulnerabilities" ? vulnPage.totalPages : licensePage.totalPages;
  const currentPage =
    view === "vulnerabilities" ? vulnPage.currentPage : licensePage.currentPage;

  useEffect(() => {
    setPage(1);
  }, [query, view, threatBand, sort, packageType]);

  useEffect(() => {
    setSort(DEFAULT_HEALTH_SORT);
  }, [view, packageType]);

  const changeSort = (key: HealthSortKey) => {
    setSort((current) => nextHealthSort(current, key));
  };

  const reportTime = formatReportTime(data?.generated_at ?? null);
  const showGroup = Boolean(
    data?.vulnerabilities.some((r) => r.group) ||
      data?.licenses.some((r) => r.group),
  );

  const downloadExcel = () => {
    const now = new Date();
    const stamp = `${now.getFullYear()}${String(now.getMonth() + 1).padStart(
      2,
      "0",
    )}${String(now.getDate()).padStart(2, "0")}_${String(
      now.getHours(),
    ).padStart(2, "0")}${String(now.getMinutes()).padStart(2, "0")}`;

    const filename = `proxy-health-${packageType}-${view}-${stamp}.xlsx`;
    const sheetName = view === "vulnerabilities" ? "취약점" : "라이선스";

    let records: Array<Record<string, unknown>>;
    if (view === "vulnerabilities") {
      records = sortedVulnRows.map((row) => {
        const out: Record<string, unknown> = {
          위험도: row.threat_level ?? "",
          "문제 코드": row.problem_code,
        };
        if (showGroup) out["그룹"] = row.group || "";
        out["이름"] = row.artifact;
        out["버전"] = row.versions || "";
        return out;
      });
    } else {
      records = sortedLicenseRows.map((row) => {
        const out: Record<string, unknown> = {
          "라이선스 위험도(라벨)": licenseThreatLabel(row.license_threat),
          "라이선스 위험도 코드": row.license_threat,
          "선언된 라이선스": row.declared_license || "",
          이름: row.artifact,
          버전: row.versions || "",
        };
        if (showGroup) out["그룹"] = row.group || "";
        return out;
      });
    }

    const ws = XLSX.utils.json_to_sheet(records, { skipHeader: false });
    if (view === "vulnerabilities") {
      sortedVulnRows.forEach((row, i) => {
        if (!row.problem_url) return;
        const cell = ws[`B${i + 2}`];
        if (cell) cell.l = { Target: row.problem_url };
      });
    }
    const wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, ws, sheetName);

    const bytes = XLSX.write(wb, { bookType: "xlsx", type: "array" });
    const blob = new Blob([bytes], {
      type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    });

    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="card health-page">
      <h2 className="card__title">{LABEL_MAP[packageType]} 패키지 보안 취약점</h2>
      <p className="request-page__hint">
        Nexus Repository Health Check 상세 리포트입니다. 보기에서 취약점과
        라이선스를 전환할 수 있습니다.
      </p>

      {loading && (
        <div className="result__loading">
          <span className="spinner" aria-hidden="true" />
          Health Check 리포트를 불러오는 중…
        </div>
      )}

      {error && !loading && <div className="result__error">{error}</div>}

      {data && !loading && !error && (
        <>
          <p className="result__meta">
            저장소 <strong>{data.repository}</strong>
            {reportTime && (
              <>
                {" "}
                · 분석 시각 <strong>{reportTime}</strong>
              </>
            )}
            {" · "}
            취약점 {vulnAllRows.length}건 · 라이선스 {licenseAllRows.length}건
          </p>

          <div className="health-page__toolbar">
            <label className="health-page__view">
              보기
              <select
                value={view}
                onChange={(e) => setView(e.target.value as ProxyHealthView)}
              >
                <option value="vulnerabilities">취약점</option>
                <option value="licenses">라이선스</option>
              </select>
            </label>
            {view === "vulnerabilities" && (
              <label className="health-page__view">
                위험도
                <select
                  value={threatBand}
                  onChange={(e) =>
                    setThreatBand(e.target.value as ThreatBand)
                  }
                >
                  <option value="all">전체</option>
                  <option value="critical">Critical (7-10)</option>
                  <option value="severe">Severe (4-6)</option>
                  <option value="moderate">Moderate (1-3)</option>
                </select>
              </label>
            )}
            <input
              className="health-page__search"
              type="search"
              placeholder={
                view === "vulnerabilities"
                  ? "패키지·CVE 검색"
                  : "패키지·라이선스 검색"
              }
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
            <button
              type="button"
              className="btn-secondary"
              disabled={!data || loading || Boolean(error) || activeCount === 0}
              onClick={downloadExcel}
            >
              엑셀 다운로드
            </button>
          </div>

          {activeCount === 0 ? (
            <div className="result__empty">해당하는 항목이 없습니다.</div>
          ) : view === "vulnerabilities" ? (
            <div className="health-page__table-wrap">
              <table className="version-table">
                <thead>
                  <tr>
                    <SortHeader
                      label="위험도"
                      column="threat"
                      sort={sort}
                      onSort={changeSort}
                    />
                    <th>문제 코드</th>
                    {showGroup && <th>그룹</th>}
                    <SortHeader
                      label="이름"
                      column="name"
                      sort={sort}
                      onSort={changeSort}
                    />
                    <th>버전</th>
                    <SortHeader
                      label="반입 날짜"
                      column="importedAt"
                      sort={sort}
                      onSort={changeSort}
                    />
                  </tr>
                </thead>
                <tbody>
                  {vulnPage.pageItems.map((row, idx) => {
                    const severity = threatSeverity(row.threat_level);
                    const threatInt = formatThreatInteger(row.threat_level);
                    return (
                      <tr key={`${row.problem_code}-${row.artifact}-${idx}`}>
                        <td>
                          <span className={`threat threat--${severity}`}>
                            {threatInt == null ? "—" : threatInt}
                          </span>
                        </td>
                        <td>
                          {row.problem_url ? (
                            <a
                              href={row.problem_url}
                              target="_blank"
                              rel="noreferrer"
                            >
                              {row.problem_code || "—"}
                            </a>
                          ) : (
                            row.problem_code || "—"
                          )}
                        </td>
                        {showGroup && <td>{row.group || "—"}</td>}
                        <td>{row.artifact}</td>
                        <td>{row.versions || "—"}</td>
                        <td>{formatImportedAt(row.imported_at) || "—"}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="health-page__table-wrap">
              <table className="version-table">
                <thead>
                  <tr>
                    <SortHeader
                      label="라이선스 위험도"
                      column="threat"
                      sort={sort}
                      onSort={changeSort}
                    />
                    <th>선언된 라이선스</th>
                    {showGroup && <th>그룹</th>}
                    <SortHeader
                      label="이름"
                      column="name"
                      sort={sort}
                      onSort={changeSort}
                    />
                    <th>버전</th>
                    <SortHeader
                      label="반입 날짜"
                      column="importedAt"
                      sort={sort}
                      onSort={changeSort}
                    />
                  </tr>
                </thead>
                <tbody>
                  {licensePage.pageItems.map((row, idx) => (
                    <tr key={`${row.artifact}-${row.versions}-${idx}`}>
                      <td>
                        <span className={licenseThreatClass(row.license_threat)}>
                          {licenseThreatLabel(row.license_threat)}
                        </span>
                      </td>
                      <td>{row.declared_license || "—"}</td>
                      {showGroup && <td>{row.group || "—"}</td>}
                      <td>{row.artifact}</td>
                      <td>{row.versions || "—"}</td>
                      <td>{formatImportedAt(row.imported_at) || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {activeCount > 0 && (
            <Pagination
              currentPage={currentPage}
              totalPages={totalPages}
              totalItems={activeCount}
              pageSize={HEALTH_PAGE_SIZE}
              onPageChange={setPage}
            />
          )}
        </>
      )}
    </div>
  );
}
