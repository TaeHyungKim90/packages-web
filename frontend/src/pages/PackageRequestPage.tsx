import { useEffect, useId, useState, type FormEvent } from "react";
import {
  fetchRequestStatus,
  requestPackage,
  validatePackageRequest,
} from "../api/client";
import type {
  PackageRequestResult,
  PackageRequestValidation,
  PackageType,
  RequestRow,
  StoredPackageRequest,
} from "../types";

const MAX_PACKAGES = 10;
const POLL_INTERVAL_MS = 10_000;
const POLL_MAX_MS = 15 * 60_000;

type RequestEco = Extract<PackageType, "pypi" | "npm">;

const LABEL_MAP: Record<PackageType, string> = {
  pypi: "PyPI",
  npm: "npm",
  nuget: "NuGet",
};

const PLACEHOLDERS: Record<RequestEco, { name: string; version: string }> = {
  pypi: { name: "예: requests", version: "예: 2.32.3" },
  npm: { name: "예: lodash 또는 @scope/pkg", version: "예: 4.17.21" },
};

interface Props {
  packageType: PackageType;
}

function storageKey(eco: RequestEco): string {
  return `packages-web:${eco}-request`;
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

function normalizeResult(
  raw: unknown,
  fallbackEco: RequestEco,
): PackageRequestResult | null {
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
    ecosystem: r.ecosystem ?? fallbackEco,
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
    delivery: r.delivery ?? "pending",
  };
}

function loadStored(eco: RequestEco): StoredPackageRequest | null {
  const key = storageKey(eco);
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as StoredPackageRequest & {
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
    if (!rows) {
      // result-only storage (current behavior)
      return {
        rows: [newRow()],
        validation: null,
        result: normalizeResult(parsed.result, eco),
      };
    }

    return {
      rows,
      validation: normalizeValidation(parsed.validation),
      result: normalizeResult(parsed.result, eco),
    };
  } catch {
    localStorage.removeItem(key);
    return null;
  }
}

function saveStored(eco: RequestEco, state: StoredPackageRequest) {
  localStorage.setItem(storageKey(eco), JSON.stringify(state));
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

/** Failed checks for display. Hosted + Inventory both fail → Hosted만 표시. */
function visibleFailedChecks(
  checks: PackageRequestValidation["items"][number]["checks"],
) {
  const failed = (checks ?? []).filter((check) => !check.passed);
  const hostedFailed = failed.some((c) => c.key === "hosted");
  if (!hostedFailed) return failed;
  return failed.filter((c) => c.key !== "inventory");
}

export default function PackageRequestPage({ packageType }: Props) {
  if (packageType !== "pypi" && packageType !== "npm") {
    return (
      <div className="card request-page--coming-soon">
        <h2 className="card__title">{LABEL_MAP[packageType]} 패키지 신청</h2>
        <p className="request-page__coming-soon">준비중</p>
      </div>
    );
  }

  return <PackageRequestForm eco={packageType} />;
}

function PackageRequestForm({ eco }: { eco: RequestEco }) {
  const formId = useId();
  const stored = loadStored(eco);
  const placeholders = PLACEHOLDERS[eco];
  const [rows, setRows] = useState<RequestRow[]>([newRow()]);
  const [validation, setValidation] = useState<PackageRequestValidation | null>(null);
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
      fetchRequestStatus(eco, prNumber, packages)
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
  }, [eco, result?.pr_number]);

  useEffect(() => {
    saveStored(eco, { rows: [], validation: null, result });
  }, [eco, result]);

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
  const hasPendingRequest = !!result && result.delivery !== "done";
  const canSubmit =
    validation?.can_request === true &&
    rowsMatchValidation(rows, validation) &&
    !submitting &&
    !validating &&
    !hasPendingRequest;

  const onValidate = async () => {
    if (!canValidate) return;
    setValidating(true);
    setError(null);
    try {
      const data = await validatePackageRequest(eco, {
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
      const data = await requestPackage(eco, {
        packages: rows.map((r) => ({ name: r.name, version: r.version })),
      });
      setResult({ ...data, delivery: data.delivery ?? "pending" });
      setRows([newRow()]);
      setValidation(null);
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
    localStorage.removeItem(storageKey(eco));
  };

  return (
    <div className="card">
      <h2 className="card__title">{LABEL_MAP[eco]} 패키지 신청</h2>
      <p className="request-page__hint">
        <strong>+</strong> 버튼으로 여러 패키지를 한 번에 신청할 수 있습니다
        (최대 {MAX_PACKAGES}개).
        <br />
        반드시 <strong>검증</strong> 후 <strong>신청</strong>해 주세요.
        이름과 버전을 정확히 입력해야 하며, 이전 신청이 완료될 때까지 추가 신청은 불가합니다.
        {eco === "npm" && (
          <>
            <br />
            scoped 패키지는 <code>@scope/name</code> 형식으로 입력하세요.
          </>
        )}
        <br />
        {MAX_PACKAGES}개를 넘는 다량의 패키지는 담당자에게 패키지 목록을 메일로 보내 주세요.
        검토 후 대신 등록해 드립니다.
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
                  placeholder={placeholders.name}
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
                  placeholder={placeholders.version}
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
            {submitting ? "신청 중…" : "신청"}
          </button>
        </div>
        {hasPendingRequest && validation?.can_request && (
          <p className="request-alert request-alert--warn" role="status">
            이전 신청이 진행 중입니다. 완료된 후 새 신청이 가능합니다.
          </p>
        )}
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
                    {visibleFailedChecks(item.checks).map((check) => (
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
            </strong>
            {result.requested_by ? ` · @${result.requested_by}` : ""}
          </p>
          {result.delivery === "done" ? (
            <div className="request-alert request-alert--success" role="status">
              Hosted에 등록되었습니다. 패키지 검색에서 확인할 수 있습니다.
            </div>
          ) : result.delivery === "delivering" ||
            result.delivery === "merged" ||
            result.merged ? (
            <p className="request-result__status" role="status">
              패키지 받는중…
            </p>
          ) : (
            <p className="request-result__status" role="status">
              패키지 검사중…
            </p>
          )}
        </div>
      )}
    </div>
  );
}
