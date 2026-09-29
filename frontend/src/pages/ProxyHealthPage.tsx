import { useCallback, useEffect, useMemo, useState } from "react";
import * as XLSX from "xlsx";
import {
  deleteProxyHealthOverride,
  fetchProxyHealth,
  fetchProxyHealthSnapshot,
  updateProxyHealthOverride,
} from "../api/client";
import Pagination from "../components/Pagination";
import VulnOverrideModal from "../components/VulnOverrideModal";
import { useAuth } from "../hooks/useAuth";
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
  filterByImportStatus,
  filterLicenses,
  filterVulnerabilities,
  filterVulnerabilitiesByBand,
  formatFixedVersions,
  formatImportedAt,
  formatReportTime,
  formatThreatInteger,
  licenseThreatClass,
  licenseThreatLabel,
  nextHealthSort,
  sortAggregatedLicenses,
  sortAggregatedVulnerabilities,
  threatSeverity,
  type AggregatedVulnerability,
  type HealthSort,
  type HealthSortKey,
  type ImportFilter,
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
  const auth = useAuth();
  const canEdit = Boolean(auth.user?.can_request);
  const [data, setData] = useState<ProxyHealthResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<ProxyHealthView>("vulnerabilities");
  const [query, setQuery] = useState("");
  const [threatBand, setThreatBand] = useState<ThreatBand>("all");
  const [importFilter, setImportFilter] = useState<ImportFilter>("all");
  const [sort, setSort] = useState<HealthSort>(DEFAULT_HEALTH_SORT);
  const [page, setPage] = useState(1);
  const [editRow, setEditRow] = useState<AggregatedVulnerability | null>(null);
  const [modalSaving, setModalSaving] = useState(false);
  const [modalError, setModalError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const loadData = useCallback(async () => {
    if (auth.isLoading || !auth.isAuthenticated) return;
    setLoading(true);
    setError(null);
    try {
      const result = canEdit
        ? await fetchProxyHealth(packageType)
        : await fetchProxyHealthSnapshot(packageType);
      setData(result);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [
    packageType,
    canEdit,
    auth.isLoading,
    auth.isAuthenticated,
  ]);

  const forceRefresh = useCallback(async () => {
    if (!canEdit || refreshing) return;
    setRefreshing(true);
    setError(null);
    try {
      const result = await fetchProxyHealth(packageType, { refresh: true });
      setData(result);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setRefreshing(false);
    }
  }, [canEdit, packageType, refreshing]);

  const reloadFromDb = useCallback(async () => {
    setModalError(null);
    try {
      const result = await fetchProxyHealthSnapshot(packageType);
      setData(result);
    } catch (err: unknown) {
      setModalError(err instanceof Error ? err.message : String(err));
    }
  }, [packageType]);

  useEffect(() => {
    setQuery("");
    setPage(1);
    setView("vulnerabilities");
    setThreatBand("all");
    setImportFilter("all");
    setSort(DEFAULT_HEALTH_SORT);
    setEditRow(null);
  }, [packageType]);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  const importFilteredVulns = useMemo(
    () => filterByImportStatus(data?.vulnerabilities ?? [], importFilter),
    [data, importFilter],
  );
  const importFilteredLicenses = useMemo(
    () => filterByImportStatus(data?.licenses ?? [], importFilter),
    [data, importFilter],
  );

  const vulnAllRows = useMemo(
    () =>
      aggregateVulnerabilities(
        importFilteredVulns,
        data?.vulnerability_overrides,
      ),
    [importFilteredVulns, data?.vulnerability_overrides],
  );
  const licenseAllRows = useMemo(
    () => aggregateLicenses(importFilteredLicenses),
    [importFilteredLicenses],
  );

  const vulnRows = useMemo(() => {
    const items = query.trim()
      ? filterVulnerabilities(importFilteredVulns, query)
      : importFilteredVulns;
    const aggregated = aggregateVulnerabilities(
      items,
      data?.vulnerability_overrides,
    );
    return filterVulnerabilitiesByBand(aggregated, threatBand);
  }, [
    importFilteredVulns,
    query,
    threatBand,
    data?.vulnerability_overrides,
  ]);

  const sortedVulnRows = useMemo(
    () => sortAggregatedVulnerabilities(vulnRows, sort),
    [vulnRows, sort],
  );
  const licenseRows = useMemo(() => {
    const items = query.trim()
      ? filterLicenses(importFilteredLicenses, query)
      : importFilteredLicenses;
    return aggregateLicenses(items);
  }, [importFilteredLicenses, query]);
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
  }, [query, view, threatBand, importFilter, sort, packageType]);

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

  const closeModal = () => {
    if (modalSaving) return;
    setEditRow(null);
    setModalError(null);
  };

  const handleSaveOverride = async (fixedVersion: string, remark: string) => {
    if (!editRow) return;
    setModalSaving(true);
    setModalError(null);
    try {
      await updateProxyHealthOverride(packageType, {
        problem_code: editRow.problem_code,
        artifact: editRow.artifact,
        fixed_version: fixedVersion.trim() || null,
        remark,
      });
      setEditRow(null);
      await reloadFromDb();
    } catch (err: unknown) {
      setModalError(err instanceof Error ? err.message : String(err));
    } finally {
      setModalSaving(false);
    }
  };

  const handleRevertOverride = async () => {
    if (!editRow) return;
    setModalSaving(true);
    setModalError(null);
    try {
      await deleteProxyHealthOverride(packageType, {
        problem_code: editRow.problem_code,
        artifact: editRow.artifact,
      });
      setEditRow(null);
      await reloadFromDb();
    } catch (err: unknown) {
      setModalError(err instanceof Error ? err.message : String(err));
    } finally {
      setModalSaving(false);
    }
  };

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
    let problemUrls: string[] = [];
    if (view === "vulnerabilities") {
      // 정상버전·오탐(resolved)은 화면 리스트에만 두고 엑셀에서는 제외
      const exportVulns = importFilteredVulns.filter((v) => !v.resolved);
      const exportRows = sortAggregatedVulnerabilities(
        filterVulnerabilitiesByBand(
          aggregateVulnerabilities(
            query.trim()
              ? filterVulnerabilities(exportVulns, query)
              : exportVulns,
            data?.vulnerability_overrides,
          ),
          threatBand,
        ),
        sort,
      );
      problemUrls = exportRows.map((row) => row.problem_url);
      records = exportRows.map((row) => {
        const out: Record<string, unknown> = {
          위험도: row.threat_level ?? "",
          "문제 코드": row.problem_code,
        };
        if (showGroup) out["그룹"] = row.group || "";
        out["이름"] = row.artifact;
        out["버전"] = row.versions || "";
        out["해결 버전"] = formatFixedVersions(row.fixed_versions);
        out["비고"] = row.remark || "";
        out["공개일"] = formatImportedAt(row.published_at) || "";
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
          "반입 날짜": formatImportedAt(row.imported_at) || "",
        };
        if (showGroup) out["그룹"] = row.group || "";
        return out;
      });
    }

    const ws = XLSX.utils.json_to_sheet(records, { skipHeader: false });
    problemUrls.forEach((url, i) => {
      if (!url) return;
      const cell = ws[`B${i + 2}`];
      if (cell) cell.l = { Target: url };
    });
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
        라이선스를 전환할 수 있습니다. 해결 버전은 DB에 있으면 재사용하고,
        없으면 OSV로 보강합니다.
      </p>

      {loading && (
        <div className="result__loading">
          <span className="spinner" aria-hidden="true" />
          Health Check 리포트를 불러오는 중…
        </div>
      )}

      {error && !loading && !refreshing && (
        <div className="result__error">{error}</div>
      )}

      {data && !loading && !error && (
        <>
          <p className="result__meta">
            저장소 <strong>{data.repository}</strong>
            {reportTime && (
              <>
                {" "}
                · 보고서 갱신 <strong>{reportTime}</strong>
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
            <label className="health-page__view">
              반입 여부
              <select
                value={importFilter}
                onChange={(e) =>
                  setImportFilter(e.target.value as ImportFilter)
                }
              >
                <option value="all">전체</option>
                <option value="hosted">반입됨</option>
                <option value="pending">반입전</option>
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
            {canEdit && (
              <button
                type="button"
                className="btn-secondary health-page__refresh"
                disabled={loading || refreshing}
                title="Nexus/OSV에서 지금 다시 가져오기"
                aria-label="취약점 목록 새로고침"
                aria-busy={refreshing}
                onClick={() => void forceRefresh()}
              >
                {refreshing ? (
                  <span className="spinner spinner--btn" aria-hidden="true" />
                ) : (
                  "♻️"
                )}
              </button>
            )}
            <button
              type="button"
              className="btn-secondary"
              disabled={
                !data || loading || refreshing || Boolean(error) || activeCount === 0
              }
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
                    <th>해결 버전</th>
                    <th>비고</th>
                    <SortHeader
                      label="공개일"
                      column="publishedAt"
                      sort={sort}
                      onSort={changeSort}
                    />
                    {canEdit && <th>수정</th>}
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
                        <td>{formatFixedVersions(row.fixed_versions)}</td>
                        <td>{row.remark || "—"}</td>
                        <td>{formatImportedAt(row.published_at) || "—"}</td>
                        {canEdit && (
                          <td>
                            <button
                              type="button"
                              className="btn-text"
                              onClick={() => {
                                setModalError(null);
                                setEditRow(row);
                              }}
                            >
                              수정
                            </button>
                          </td>
                        )}
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

      {canEdit && (
        <VulnOverrideModal
          open={editRow != null}
          row={editRow}
          saving={modalSaving}
          error={modalError}
          onClose={closeModal}
          onSave={handleSaveOverride}
          onRevert={handleRevertOverride}
        />
      )}
    </div>
  );
}
