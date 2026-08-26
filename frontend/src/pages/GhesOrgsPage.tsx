import { useCallback, useEffect, useState } from "react";
import { fetchGhesOrgs, saveGhesOrgs, syncGhesOrgs } from "../api/client";
import type { GhesOrgItem } from "../types";
import { formatReportTime } from "../utils/health";

export default function GhesOrgsPage() {
  const [orgs, setOrgs] = useState<GhesOrgItem[]>([]);
  const [syncedAt, setSyncedAt] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

  const applyData = useCallback((data: { organizations: GhesOrgItem[]; synced_at: string | null }) => {
    setOrgs(data.organizations);
    setSyncedAt(data.synced_at);
    setExpanded((prev) => {
      const next = { ...prev };
      for (const org of data.organizations) {
        if (next[org.name] === undefined) next[org.name] = false;
      }
      return next;
    });
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    setMessage(null);
    try {
      const data = await fetchGhesOrgs();
      applyData(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [applyData]);

  useEffect(() => {
    void load();
  }, [load]);

  const toggleOrgManaged = (orgName: string) => {
    setOrgs((prev) =>
      prev.map((o) =>
        o.name === orgName ? { ...o, managed: !o.managed } : o,
      ),
    );
    setMessage(null);
  };

  const toggleRepoManaged = (orgName: string, repoName: string) => {
    setOrgs((prev) =>
      prev.map((o) =>
        o.name !== orgName
          ? o
          : {
              ...o,
              repos: o.repos.map((r) =>
                r.name === repoName ? { ...r, managed: !r.managed } : r,
              ),
            },
      ),
    );
    setMessage(null);
  };

  const handleSync = async () => {
    setSyncing(true);
    setError(null);
    setMessage(null);
    try {
      const data = await syncGhesOrgs();
      applyData(data);
      setMessage("GHES에서 조직·레포를 동기화해 DB에 저장했습니다.");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSyncing(false);
    }
  };

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    setMessage(null);
    try {
      const data = await saveGhesOrgs(orgs);
      applyData(data);
      setMessage("관리 대상 설정을 DB에 저장했습니다.");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  const busy = loading || saving || syncing;

  return (
    <section className="card orgs-page">
      <div className="orgs-page__header">
        <h2 className="card__title">GHES 조직 · 레포</h2>
        <div className="orgs-page__actions">
          <button
            type="button"
            className="btn-secondary"
            onClick={() => void load()}
            disabled={busy}
          >
            새로고침
          </button>
          <button
            type="button"
            className="btn-secondary"
            onClick={() => void handleSync()}
            disabled={busy}
          >
            {syncing ? "동기화 중…" : "동기화"}
          </button>
          <button
            type="button"
            className="btn-primary"
            onClick={() => void handleSave()}
            disabled={busy || orgs.length === 0}
          >
            {saving ? "저장 중…" : "저장"}
          </button>
        </div>
      </div>
      <p className="orgs-page__hint">
        목록은 DB 캐시입니다. <strong>동기화</strong>로 GHES에서 조직·레포를
        갱신하고, <strong>저장</strong>으로 관리 대상 플래그만 DB에 반영합니다.
      </p>
      {syncedAt && (
        <p className="orgs-page__meta">마지막 동기화: {formatReportTime(syncedAt)}</p>
      )}

      {loading && (
        <p className="orgs-page__status">
          <span className="spinner" aria-hidden="true" />
          불러오는 중…
        </p>
      )}
      {error && <p className="orgs-page__error">{error}</p>}
      {message && <p className="orgs-page__ok">{message}</p>}

      {!loading && !error && orgs.length === 0 && (
        <p className="orgs-page__empty">
          조직이 없습니다. 동기화로 GHES에서 불러오세요.
        </p>
      )}

      <ul className="orgs-list">
        {orgs.map((org) => {
          const open = Boolean(expanded[org.name]);
          return (
            <li key={org.name} className="orgs-list__org">
              <div className="orgs-list__org-row">
                <button
                  type="button"
                  className="orgs-list__toggle"
                  aria-expanded={open}
                  onClick={() =>
                    setExpanded((prev) => ({
                      ...prev,
                      [org.name]: !prev[org.name],
                    }))
                  }
                >
                  {open ? "▾" : "▸"} {org.name}
                  {!org.present && (
                    <span className="orgs-list__badge">미발견</span>
                  )}
                </button>
                <label className="orgs-list__managed">
                  <input
                    type="checkbox"
                    checked={org.managed}
                    onChange={() => toggleOrgManaged(org.name)}
                  />
                  관리 대상
                </label>
              </div>
              {open && (
                <ul className="orgs-list__repos">
                  {org.repos.length === 0 && (
                    <li className="orgs-list__empty-repo">레포 없음</li>
                  )}
                  {org.repos.map((repo) => (
                    <li key={repo.name} className="orgs-list__repo-row">
                      <span>
                        {repo.name}
                        {!repo.present && (
                          <span className="orgs-list__badge">미발견</span>
                        )}
                      </span>
                      <label className="orgs-list__managed">
                        <input
                          type="checkbox"
                          checked={repo.managed}
                          onChange={() =>
                            toggleRepoManaged(org.name, repo.name)
                          }
                        />
                        관리 대상
                      </label>
                    </li>
                  ))}
                </ul>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
