import type { PackageType } from "../types";

const PACKAGE_TYPES: PackageType[] = ["pypi", "npm", "nuget"];

interface Props {
  packageType: PackageType;
  name: string;
  version: string;
  loading: boolean;
  onPackageTypeChange: (type: PackageType) => void;
  onNameChange: (name: string) => void;
  onVersionChange: (version: string) => void;
  onSubmit: () => void;
}

export default function SearchForm({
  packageType,
  name,
  version,
  loading,
  onPackageTypeChange,
  onNameChange,
  onVersionChange,
  onSubmit,
}: Props) {
  const canSubmit = name.trim().length > 0 && !loading;

  return (
    <div className="card">
      <h2 className="card__title">패키지 확인</h2>
      <form
        className="search-form"
        onSubmit={(e) => {
          e.preventDefault();
          if (canSubmit) onSubmit();
        }}
      >
        <div className="search-form__fields">
          <div className="field">
            <label htmlFor="format">포맷</label>
            <select
              id="format"
              value={packageType}
              onChange={(e) => onPackageTypeChange(e.target.value as PackageType)}
            >
              {PACKAGE_TYPES.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </div>

          <div className="field">
            <label htmlFor="name">
              패키지 이름 <span aria-hidden="true">*</span>
            </label>
            <input
              id="name"
              type="text"
              value={name}
              onChange={(e) => onNameChange(e.target.value)}
              placeholder="예: uv, requests, lodash"
              autoComplete="off"
              required
            />
          </div>

          <div className="field">
            <label htmlFor="version">버전 (선택)</label>
            <input
              id="version"
              type="text"
              value={version}
              onChange={(e) => onVersionChange(e.target.value)}
              placeholder="예: 13 또는 2.32.3"
              autoComplete="off"
            />
          </div>
        </div>

        <div className="search-form__footer">
          <p className="search-form__hint">
            이름·버전 모두 일부만 입력해도 검색됩니다 (예: uv → uvicorn, 13 → 17.13.9).
          </p>

          <div className="search-form__actions">
            <button type="submit" className="btn-primary" disabled={!canSubmit}>
              {loading ? "검색 중…" : "검색"}
            </button>
          </div>
        </div>
      </form>
    </div>
  );
}
