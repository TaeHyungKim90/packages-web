import { useEffect, useId, useState, type FormEvent } from "react";
import {
  fetchPypiRequestStatus,
  requestPypiPackage,
  validatePypiPackage,
} from "../api/client";
import type {
  PackageRequestResult,
  PackageRequestValidation,
  PackageType,
  RequestRow,
  StoredPypiRequest,
} from "../types";

const STORAGE_KEY = "packages-web:pypi-request";
const MAX_PACKAGES = 10;
const POLL_INTERVAL_MS = 30_000;
const POLL_MAX_MS = 15 * 60_000;

const LABEL_MAP: Record<PackageType, string> = {
  pypi: "PyPI",
  npm: "npm",
  nuget: "NuGet",
};

interface Props {
  packageType: PackageType;
}

function newRow(partial?: Partial<RequestRow>): RequestRow {
  return {
    id:
      typeof crypto !== "undefined" && "randomUUID" in crypto
        ? crypto.randomUUID()
        : `row-${Date.now()}-${Math.random().toString(36).slice(2)}`,
    name: partial?.name ?? "",
    version: partial?.version ?? "",
  };
}

function normalizeValidation(raw: unknown): PackageRequestValidation | null {
  if (!raw || typeof raw !== "object") return null;
  const v = raw as Partial<PackageRequestValidation> & {
    name?: string;
    version?: string;
    checks?: PackageRequestValidation["items"][number]["checks"];
  };
  if (Array.isArray(v.items)) {
    return {
      can_request: Boolean(v.can_request),
      items: v.items,
    };
  }
  // Legacy single-item validation
  if (v.name && v.version && Array.isArray(v.checks)) {
    return {
      can_request: Boolean(v.can_request),
      items: [
        {
          name: v.name,
          version: v.version,
          can_request: Boolean(v.can_request),
          checks: v.checks,
        },
      ],
    };
  }
  return null;
}

function normalizeResult(raw: unknown): PackageRequestResult | null {
  if (!raw || typeof raw !== "object") return null;
  const r = raw as Partial<PackageRequestResult> & {
    name?: string;
    version?: string;
  };
  if (!r.pr_number || !r.pr_url) return null;
  const packages = Array.isArray(r.packages)
    ? r.packages
    : r.name && r.version
      ? [{ name: r.name, version: r.version }]
      : null;
  if (!packages?.length) return null;
  return {
    ecosystem: r.ecosystem ?? "pypi",
    packages,
    repository: r.repository ?? "",
    branch: r.branch ?? "",
    pr_number: r.pr_number,
    pr_url: r.pr_url,
    pr_state: r.pr_state ?? "open",
    merged: Boolean(r.merged),
    automerge: Boolean(r.automerge),
    automerge_detail: r.automerge_detail ?? "",
    requested_by: r.requested_by ?? "",
    delivery: r.delivery,
  };
}

function loadStored(): StoredPypiRequest | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as StoredPypiRequest & {
      name?: string;
      version?: string;
    };

    let rows: RequestRow[] | null = null;
    if (Array.isArray(parsed.rows) && parsed.rows.length > 0) {
      rows = parsed.rows
        .slice(0, MAX_PACKAGES)
        .map((row) => newRow({ name: row.name ?? "", version: row.version ?? "" }));
    } else if (parsed.name || parsed.version) {
      rows = [newRow({ name: parsed.name ?? "", version: parsed.version ?? "" })];
    }
    if (!rows) return null;

    return {
      rows,
      validation: normalizeValidation(parsed.validation),
      result: normalizeResult(parsed.result),
    };
  } catch {
    localStorage.removeItem(STORAGE_KEY);
    return null;
  }
}

function saveStored(state: StoredPypiRequest) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
}

function rowsMatchValidation(
  rows: RequestRow[],
  validation: PackageRequestValidation | null,
): boolean {
  if (!validation?.items || validation.items.length !== rows.length) return false;
  return rows.every((row, i) => {
    const item = validation.items[i];
    return item.name === row.name.trim() && item.version === row.version.trim();
  });
}

export default function PackageRequestPage({ packageType }: Props) {
  if (packageType !== "pypi") {
    return (
      <div className="card request-page--coming-soon">
        <h2 className="card__title">{LABEL_MAP[packageType]} 패키지 신청</h2>
        <p className="request-page__coming-soon">준비중</p>
      </div>
    );
  }

  return <PypiRequestForm />;
}

function PypiRequestForm() {
  const formId = useId();
  const stored = loadStored();
  const [rows, setRows] = useState<RequestRow[]>(
    stored?.rows?.length ? stored.rows : [newRow()],
  );
  const [validation, setValidation] = useState<PackageRequestValidation | null>(
    stored?.validation ?? null,
  );
  const [result, setResult] = useState<PackageRequestResult | null>(
    stored?.result ?? null,
  );
  const [validating, setValidating] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!result?.pr_number || !result.packages?.length) return;
    if (result.delivery === "done") return;

    let cancelled = false;
    let intervalId = 0;
    const startedAt = Date.now();
    const prNumber = result.pr_number;
    const packages = result.packages;

    const refresh = () => {
      fetchPypiRequestStatus(prNumber, packages)
        .then((status) => {
          if (cancelled) return;
          setResult((prev) =>
            prev
              ? {
                  ...prev,
                  pr_state: status.pr_state,
                  merged: status.merged,
                  pr_url: status.pr_url,
                  delivery: status.delivery,
                }
              : prev,
          );
          if (status.delivery === "done") {
            window.clearInterval(intervalId);
          }
        })
        .catch(() => {
          /* keep cached result */
        });
    };

    refresh();
    intervalId = window.setInterval(() => {
      if (Date.now() - startedAt >= POLL_MAX_MS) {
        window.clearInterval(intervalId);
        return;
      }
      refresh();
    }, POLL_INTERVAL_MS);

    return () => {
      cancelled = true;
      window.clearInterval(intervalId);
    };
    // Poll for this PR until done or unmount; do not restart on each delivery tick.
    // eslint-disable-next-line react-hooks/exhaustive-deps -- intentional
  }, [result?.pr_number]);

  useEffect(() => {
    saveStored({ rows, validation, result });
  }, [rows, validation, result]);

  const updateRow = (id: string, patch: Partial<Pick<RequestRow, "name" | "version">>) => {
    setRows((prev) => prev.map((row) => (row.id === id ? { ...row, ...patch } : row)));
    setValidation(null);
    setError(null);
  };

  const addRow = () => {
    setRows((prev) => (prev.length >= MAX_PACKAGES ? prev : [...prev, newRow()]));
    setValidation(null);
    setError(null);
  };

  const removeRow = (id: string) => {
    setRows((prev) => (prev.length <= 1 ? prev : prev.filter((row) => row.id !== id)));
    setValidation(null);
    setError(null);
  };

  const filled = rows.every((r) => r.name.trim() && r.version.trim());
  const canValidate = filled && !validating && !submitting;
  const canSubmit =
    validation?.can_request === true &&
    rowsMatchValidation(rows, validation) &&
    !submitting &&
    !validating;

  const onValidate = async () => {
    if (!canValidate) return;
    setValidating(true);
    setError(null);
    try {
      const data = await validatePypiPackage({
        packages: rows.map((r) => ({ name: r.name, version: r.version })),
      });
      setValidation(data);
    } catch (err) {
      setValidation(null);
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setValidating(false);
    }
  };

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!canSubmit) return;

    setSubmitting(true);
    setError(null);
    try {
      const data = await requestPypiPackage({
        packages: rows.map((r) => ({ name: r.name, version: r.version })),
      });
      setResult(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  };

  const clearHistory = () => {
    setResult(null);
    setValidation(null);
    setError(null);
    localStorage.removeItem(STORAGE_KEY);
  };

  return (
    <div className="card">
      <h2 className="card__title">PyPI 패키지 신청</h2>
      <p className="request-page__hint">
        신청 전 <strong>검증</strong>으로 업스트림 버전 존재·Hosted·inventory·요청 목록을
        확인합니다. <strong>+</strong>로 여러 패키지를 한 PR에 신청할 수 있습니다
        (최대 {MAX_PACKAGES}개).
      </p>

      <form className="search-form" onSubmit={(e) => void onSubmit(e)}>
        <div className="request-rows">
          {rows.map((row, index) => (
            <div key={row.id} className="request-rows__item">
              <div className="field">
                {index === 0 && <label htmlFor={`${formId}-name-${row.id}`}>패키지 이름</label>}
                <input
                  id={`${formId}-name-${row.id}`}
                  type="text"
                  value={row.name}
                  onChange={(e) => updateRow(row.id, { name: e.target.value })}
                  placeholder="예: requests"
                  autoComplete="off"
                  required
                  aria-label={`패키지 이름 ${index + 1}`}
                />
              </div>
              <div className="field">
                {index === 0 && (
                  <label htmlFor={`${formId}-version-${row.id}`}>버전</label>
                )}
                <input
                  id={`${formId}-version-${row.id}`}
                  type="text"
                  value={row.version}
                  onChange={(e) => updateRow(row.id, { version: e.target.value })}
                  placeholder="예: 2.32.3"
                  autoComplete="off"
                  required
                  aria-label={`버전 ${index + 1}`}
                />
              </div>
              <div
                className={`request-rows__controls${index === 0 ? " request-rows__controls--labeled" : ""}`}
              >
                <button
                  type="button"
                  className="btn-circle"
                  onClick={addRow}
                  disabled={rows.length >= MAX_PACKAGES}
                  aria-label="패키지 행 추가"
                  title={
                    rows.length >= MAX_PACKAGES
                      ? `최대 ${MAX_PACKAGES}개까지 신청할 수 있습니다`
                      : "추가"
                  }
                >
                  +
                </button>
                <button
                  type="button"
                  className="btn-circle btn-circle--danger"
                  onClick={() => removeRow(row.id)}
                  disabled={rows.length <= 1}
                  aria-label="패키지 행 삭제"
                  title="삭제"
                >
                  −
                </button>
              </div>
            </div>
          ))}
        </div>

        <div className="search-form__actions request-form__actions">
          <button
            type="button"
            className="btn-secondary"
            disabled={!canValidate}
            onClick={() => void onValidate()}
          >
            {validating ? "검증 중…" : "검증"}
          </button>
          <button type="submit" className="btn-primary" disabled={!canSubmit}>
            {submitting ? "신청 중…" : "신청 (PR 생성)"}
          </button>
        </div>
      </form>

      {validation?.items && validation.items.length > 0 && (
        validation.can_request ? (
          <div className="request-alert request-alert--success" role="status">
            검증 통과 — 신청할 수 있습니다.
          </div>
        ) : (
          <div className="request-validation-list">
            {validation.items
              .filter((item) => !item.can_request)
              .map((item) => (
                <div
                  key={`${item.name}==${item.version}`}
                  className="request-validation-block"
                >
                  <h3 className="request-validation-block__title">
                    {item.name}=={item.version}
                    <span className="request-validation-block__badge--fail">실패</span>
                  </h3>
                  <ul className="request-checks">
                    {(item.checks ?? [])
                      .filter((check) => !check.passed)
                      .map((check) => (
                        <li key={check.key} className="request-checks__item--fail">
                          <span className="request-checks__label">{check.label}</span>
                          <span className="request-checks__detail">{check.detail}</span>
                        </li>
                      ))}
                  </ul>
                </div>
              ))}
          </div>
        )
      )}

      {error && <div className="result__error">{error}</div>}

      {result?.packages && result.packages.length > 0 && (
        <div className="request-result">
          <div className="request-result__header">
            <span className="badge badge--success">최근 신청</span>
            <button type="button" className="btn-text" onClick={clearHistory}>
              기록 지우기
            </button>
          </div>
          <p className="result__meta">
            <strong>
              {result.packages.map((p) => `${p.name}==${p.version}`).join(", ")}
            </strong>{" "}
            · {result.repository} · @{result.requested_by}
          </p>
          <p className="request-result__pr">
            <a href={result.pr_url} target="_blank" rel="noreferrer">
              PR #{result.pr_number}
            </a>
            <span className="request-result__state">
              {result.merged ? "merged" : result.pr_state}
              {result.automerge
                ? ` · automerge 요청됨${result.automerge_detail ? ` (${result.automerge_detail})` : ""}`
                : result.automerge_detail
                  ? ` · automerge 실패: ${result.automerge_detail}`
                  : ""}
            </span>
          </p>
          <p className="request-result__branch">branch: {result.branch}</p>
          {result.delivery === "done" ? (
            <div className="request-alert request-alert--success" role="status">
              Hosted에 등록되었습니다. 패키지 검색에서 확인할 수 있습니다.
            </div>
          ) : result.delivery === "delivering" ||
            result.delivery === "merged" ||
            result.merged ? (
            <p className="request-result__note">Hosted 등록 확인 중…</p>
          ) : (
            <p className="request-result__note">
              새로고침해도 이 브라우저에 최근 신청이 남습니다. CI 통과 후 병합됩니다.
            </p>
          )}
        </div>
      )}
    </div>
  );
}
