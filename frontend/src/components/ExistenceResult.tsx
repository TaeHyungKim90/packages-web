import { useEffect, useState } from "react";
import type { PackageCheckResponse } from "../types";
import { highlightMatch } from "../utils/highlight";
import { PAGE_SIZE, paginate } from "../utils/result";

interface Props {
  result: PackageCheckResponse | null;
  queriedVersion: string;
  loading: boolean;
  error: string | null;
  searched: boolean;
  onLoadMore?: () => void;
}

interface ResultRow {
  name: string;
  version: string;
}

export default function ExistenceResult({
  result,
  queriedVersion,
  loading,
  error,
  searched,
  onLoadMore,
}: Props) {
  const [page, setPage] = useState(1);

  const rows: ResultRow[] =
    result?.packages.flatMap((pkg) =>
      pkg.versions.map((version) => ({ name: pkg.name, version })),
    ) ?? [];

  const { pageItems: pageRows, totalPages, currentPage, start } = paginate(
    rows,
    page,
    PAGE_SIZE,
  );
  const showPaging = rows.length > PAGE_SIZE;

  useEffect(() => {
    setPage(1);
  }, [result?.query, result?.format, result?.repository, queriedVersion]);

  if (!searched && !loading && !error) {
    return null;
  }

  return (
    <div className="card">
      <h2 className="card__title">검색 결과</h2>

      {loading && !result && (
        <div className="result__loading">
          <span className="spinner" aria-hidden="true" />
          Hosted 저장소를 조회하는 중…
        </div>
      )}

      {error && !loading && <div className="result__error">{error}</div>}

      {result && !error && (
        <div className="result">
          <div className="result__badge-row">
            <StatusBadge result={result} queriedVersion={queriedVersion} />
          </div>

          <p className="result__meta">
            검색어 <strong>{result.query}</strong> · {result.format} ·{" "}
            <strong>{result.repository}</strong>
            {rows.length > 0 && (
              <>
                {" "}
                · 결과 {rows.length}건
                {showPaging && (
                  <>
                    {" "}
                    ({start + 1}–{Math.min(start + PAGE_SIZE, rows.length)})
                  </>
                )}
              </>
            )}
          </p>

          {rows.length > 0 ? (
            <>
              <table className="version-table">
                <thead>
                  <tr>
                    <th>패키지</th>
                    <th>버전</th>
                  </tr>
                </thead>
                <tbody>
                  {pageRows.map((row) => (
                    <tr key={`${row.name}@${row.version}`}>
                      <td>{row.name}</td>
                      <td
                        className={
                          queriedVersion &&
                          row.version
                            .toLowerCase()
                            .includes(queriedVersion.toLowerCase())
                            ? "version-match"
                            : ""
                        }
                      >
                        {highlightMatch(row.version, queriedVersion)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>

              {showPaging && (
                <div className="pagination" role="navigation" aria-label="결과 페이지">
                  <button
                    type="button"
                    className="pagination__btn"
                    disabled={currentPage <= 1}
                    onClick={() => setPage((p) => Math.max(1, p - 1))}
                  >
                    이전
                  </button>
                  <span className="pagination__info">
                    {currentPage} / {totalPages}
                  </span>
                  <button
                    type="button"
                    className="pagination__btn"
                    disabled={currentPage >= totalPages}
                    onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                  >
                    다음
                  </button>
                </div>
              )}
            </>
          ) : (
            !loading && <div className="result__empty">Hosted에 없습니다.</div>
          )}

          {result.continuation_token && !loading && onLoadMore && (
            <button
              type="button"
              className="btn-load-more"
              onClick={onLoadMore}
            >
              더 불러오기
            </button>
          )}

          {loading && result && (
            <div className="result__loading result__loading--inline">
              <span className="spinner" aria-hidden="true" />
              추가 결과를 불러오는 중…
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function StatusBadge({
  result,
  queriedVersion,
}: {
  result: PackageCheckResponse;
  queriedVersion: string;
}) {
  const count = result.packages.length;

  if (queriedVersion) {
    if (result.matched_version) {
      return (
        <span className="badge badge--success">
          “{queriedVersion}” 포함 버전 · 패키지 {count}개
        </span>
      );
    }
    return <span className="badge badge--neutral">해당 버전 없음</span>;
  }

  if (result.exists) {
    return (
      <span className="badge badge--success">
        {count}개 패키지 발견
      </span>
    );
  }

  return <span className="badge badge--neutral">Hosted에 없음</span>;
}
