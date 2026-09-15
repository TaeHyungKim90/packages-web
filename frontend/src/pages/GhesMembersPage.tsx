import { useCallback, useEffect, useMemo, useState } from "react";
import * as XLSX from "xlsx";
import { fetchGhesMembers, syncGhesMembers } from "../api/client";
import type { GhesMemberItem } from "../types";
import { formatReportTime } from "../utils/health";

export default function GhesMembersPage() {
  const [members, setMembers] = useState<GhesMemberItem[]>([]);
  const [syncedAt, setSyncedAt] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [query, setQuery] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchGhesMembers();
      setMembers(data.members);
      setSyncedAt(data.synced_at);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return members;
    return members.filter((m) => {
      const hay = [
        m.login,
        m.name ?? "",
        m.email ?? "",
        m.organizations_label,
        ...m.organizations,
      ]
        .join(" ")
        .toLowerCase();
      return hay.includes(q);
    });
  }, [members, query]);

  const handleSync = async () => {
    setSyncing(true);
    setError(null);
    setMessage(null);
    try {
      const data = await syncGhesMembers();
      setMembers(data.members);
      setSyncedAt(data.synced_at);
      setMessage(`동기화 완료 (${data.members.length}명)`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSyncing(false);
    }
  };

  const downloadExcel = () => {
    const rows = filtered.map((m, i) => ({
      번호: i + 1,
      로그인계정: m.login,
      조직: m.organizations_label || "",
      이름: m.name || "",
      이메일: m.email || "",
    }));
    const ws = XLSX.utils.json_to_sheet(rows);
    const wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, ws, "가입자");
    const stamp = new Date().toISOString().slice(0, 10);
    XLSX.writeFile(wb, `ghes-members-${stamp}.xlsx`);
  };

  return (
    <section className="card orgs-page">
      <div className="orgs-page__header">
        <h2 className="card__title">GHES 가입자</h2>
        <div className="orgs-page__actions">
          <button
            type="button"
            className="btn-primary proj-pkg__sync"
            onClick={() => void handleSync()}
            disabled={loading || syncing}
            aria-busy={syncing}
          >
            {syncing ? (
              <>
                <span
                  className="spinner spinner--btn spinner--on-primary"
                  aria-hidden="true"
                />
                동기화 중…
              </>
            ) : (
              "동기화"
            )}
          </button>
          <button
            type="button"
            className="btn-secondary"
            onClick={downloadExcel}
            disabled={loading || syncing || filtered.length === 0}
          >
            엑셀 다운로드
          </button>
        </div>
      </div>
      <p className="orgs-page__hint">
        GHES 전체 가입자와 소속 조직입니다. 조직·Bot 계정은 제외하고, 조직{" "}
        <code>sk-inc</code>는 소속에서 빼며, 관리 계정은 조직 열에{" "}
        <strong>관리</strong>로 표시합니다. 마지막 동기화:{" "}
        {formatReportTime(syncedAt) || "-"}
      </p>

      <div className="health-page__toolbar">
        <input
          className="health-page__search"
          type="search"
          placeholder="로그인·이름·조직 검색"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </div>

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
          <p className="result__meta">가입자 {filtered.length}명</p>
          {filtered.length === 0 ? (
            <div className="result__empty">
              {members.length === 0
                ? "저장된 가입자가 없습니다. 동기화를 실행하세요."
                : "검색 결과가 없습니다."}
            </div>
          ) : (
            <div className="health-page__table-wrap">
              <table className="version-table">
                <thead>
                  <tr>
                    <th>번호</th>
                    <th>로그인계정</th>
                    <th>조직</th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((m, i) => (
                    <tr key={m.login}>
                      <td>{i + 1}</td>
                      <td>{m.login}</td>
                      <td>{m.organizations_label || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </section>
  );
}
