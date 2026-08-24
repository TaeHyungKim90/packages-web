import { useCallback, useEffect, useState } from "react";
import { fetchGhesOrgs, saveGhesOrgs } from "../api/client";
import type { GhesOrgItem } from "../types";

export default function GhesOrgsPage() {
  const [orgs, setOrgs] = useState<GhesOrgItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    setMessage(null);
    try {
      const data = await fetchGhesOrgs();
      setOrgs(data.organizations);
      setExpanded((prev) => {
        const next = { ...prev };
        for (const org of data.organizations) {
          if (next[org.name] === undefined) next[org.name] = false;
        }
        return next;
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

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

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    setMessage(null);
    try {
      const data = await saveGhesOrgs(orgs);
      setOrgs(data.organizations);
      setMessage("config/ghes-orgs.yaml 에 저장했습니다.");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  return (
    <section className="card orgs-page">
      <div className="orgs-page__header">
        <h2 className="card__title">GHES 조직 · 레포</h2>
        <div className="orgs-page__actions">
          <button
            type="button"
            className="btn-secondary"
            onClick={() => void load()}
            disabled={loading || saving}
          >
            새로고침
          </button>
          <button
            type="button"
            className="btn-primary"
            onClick={() => void handleSave()}
            disabled={loading || saving || orgs.length === 0}
          >
            {saving ? "저장 중…" : "저장"}
          </button>
        </div>
      </div>
      <p className="orgs-page__hint">
        GHES에서 조직·레포를 불러오고, 관리 대상 여부는{" "}
        <code>config/ghes-orgs.yaml</code>에 저장됩니다.
      </p>

      {loading && (
        <p className="orgs-page__status">
          <span className="spinner" aria-hidden="true" />
          불러오는 중…
        </p>
      )}
      {error && <p className="orgs-page__error">{error}</p>}
      {message && <p className="orgs-page__ok">{message}</p>}

      {!loading && !error && orgs.length === 0 && (
        <p className="orgs-page__empty">조직이 없습니다.</p>
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
