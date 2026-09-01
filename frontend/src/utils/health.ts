import type {
  ProxyHealthLicense,
  ProxyHealthVulnOverride,
  ProxyHealthVulnerability,
} from "../types";

export const HEALTH_PAGE_SIZE = 10;

export type ImportFilter = "all" | "hosted" | "pending";

export function filterByImportStatus<
  T extends { in_hosted?: boolean | null },
>(items: T[], filter: ImportFilter): T[] {
  if (filter === "all") return items;
  if (filter === "hosted") return items.filter((item) => Boolean(item.in_hosted));
  return items.filter((item) => !item.in_hosted);
}

export function formatFixedVersions(value: string): string {
  return value.trim() || "미해결";
}

export function vulnOverrideKey(
  problemCode: string,
  artifact: string,
): string {
  return `${problemCode}\0${artifact}`;
}

function overrideMap(
  overrides: ProxyHealthVulnOverride[] | undefined,
): Map<string, ProxyHealthVulnOverride> {
  const map = new Map<string, ProxyHealthVulnOverride>();
  for (const item of overrides ?? []) {
    map.set(vulnOverrideKey(item.problem_code, item.artifact), item);
  }
  return map;
}

const LICENSE_LABELS: Record<string, string> = {
  LIBERAL: "허용적",
  WEAKCOPYLEFT: "약한 카피레프트",
  COPYLEFT: "카피레프트",
  "NON-STANDARD": "비표준",
  "NOT-PROVIDED": "미제공",
  UNKCAT: "알 수 없음",
};

export function licenseThreatLabel(raw: string): string {
  const key = raw.trim().toUpperCase();
  return LICENSE_LABELS[key] ?? (raw || "—");
}

export function licenseThreatClass(raw: string): string {
  const key = raw.trim().toUpperCase();
  switch (key) {
    case "COPYLEFT":
      return "license-threat license-threat--copyleft";
    case "NON-STANDARD":
      return "license-threat license-threat--non-standard";
    case "NOT-PROVIDED":
      return "license-threat license-threat--not-provided";
    case "WEAKCOPYLEFT":
      return "license-threat license-threat--weak-copyleft";
    case "LIBERAL":
      return "license-threat license-threat--liberal";
    default:
      return "license-threat";
  }
}

/** Higher number = higher risk (Nexus License Analysis Summary order). */
const LICENSE_THREAT_RANK: Record<string, number> = {
  COPYLEFT: 5,
  "NON-STANDARD": 4,
  "NOT-PROVIDED": 3,
  WEAKCOPYLEFT: 2,
  LIBERAL: 1,
  UNKCAT: 0,
};

export function licenseThreatRank(raw: string): number {
  return LICENSE_THREAT_RANK[raw.trim().toUpperCase()] ?? 0;
}

export function sortLicensesByThreat(
  items: ProxyHealthLicense[],
): ProxyHealthLicense[] {
  return [...items].sort((a, b) => {
    const rankDiff = licenseThreatRank(b.license_threat) - licenseThreatRank(a.license_threat);
    if (rankDiff !== 0) return rankDiff;
    return a.artifact.localeCompare(b.artifact, undefined, {
      sensitivity: "base",
    });
  });
}

export interface AggregatedLicense {
  license_threat: string;
  declared_license: string;
  observed_licenses: string;
  group: string;
  artifact: string;
  versions: string;
  security_issues: number | null;
  imported_at: string | null;
}

export function aggregateLicenses(
  items: ProxyHealthLicense[],
): AggregatedLicense[] {
  const map = new Map<
    string,
    {
      license_threat: string;
      declared_license: string;
      observed_licenses: string;
      group: string;
      artifact: string;
      versions: Set<string>;
      security_issues: number | null;
      imported_at: string | null;
    }
  >();

  for (const item of items) {
    const key = [
      item.group,
      item.artifact,
      item.license_threat,
      item.declared_license,
    ].join("\0");
    let entry = map.get(key);
    if (!entry) {
      entry = {
        license_threat: item.license_threat,
        declared_license: item.declared_license,
        observed_licenses: item.observed_licenses,
        group: item.group,
        artifact: item.artifact,
        versions: new Set(),
        security_issues: item.security_issues,
        imported_at: item.imported_at ?? null,
      };
      map.set(key, entry);
    }
    if (item.version) {
      entry.versions.add(item.version);
    }
    entry.imported_at = laterImportedAt(entry.imported_at, item.imported_at);
    if (item.security_issues != null) {
      if (
        entry.security_issues == null ||
        item.security_issues > entry.security_issues
      ) {
        entry.security_issues = item.security_issues;
      }
    }
  }

  return [...map.values()]
    .map((entry) => ({
      license_threat: entry.license_threat,
      declared_license: entry.declared_license,
      observed_licenses: entry.observed_licenses,
      group: entry.group,
      artifact: entry.artifact,
      versions: sortVersions(entry.versions),
      security_issues: entry.security_issues,
      imported_at: entry.imported_at,
    }))
    .sort((a, b) => {
      const rankDiff =
        licenseThreatRank(b.license_threat) - licenseThreatRank(a.license_threat);
      if (rankDiff !== 0) return rankDiff;
      return a.artifact.localeCompare(b.artifact, undefined, {
        sensitivity: "base",
      });
    });
}

export function formatThreatInteger(score: number | null): number | null {
  if (score == null) return null;
  return Math.trunc(score);
}

export type ThreatBand = "all" | "critical" | "severe" | "moderate";

export function matchesThreatBand(
  score: number | null,
  band: ThreatBand,
): boolean {
  if (band === "all") return true;
  const level = formatThreatInteger(score);
  if (level == null) return false;
  switch (band) {
    case "critical":
      return level >= 7 && level <= 10;
    case "severe":
      return level >= 4 && level <= 6;
    case "moderate":
      return level >= 1 && level <= 3;
  }
}

export function filterVulnerabilitiesByBand(
  rows: AggregatedVulnerability[],
  band: ThreatBand,
): AggregatedVulnerability[] {
  if (band === "all") return rows;
  return rows.filter((row) => matchesThreatBand(row.threat_level, band));
}

export function threatSeverity(
  score: number | null,
): "critical" | "severe" | "moderate" | "none" {
  const level = formatThreatInteger(score);
  if (level == null) return "none";
  if (level >= 7) return "critical";
  if (level >= 4) return "severe";
  return "moderate";
}

export interface AggregatedVulnerability {
  threat_level: number | null;
  problem_code: string;
  problem_url: string;
  group: string;
  artifact: string;
  versions: string;
  fixed_versions: string;
  remark: string;
  has_override: boolean;
  imported_at: string | null;
}

function sortVersions(values: Iterable<string>): string {
  return [...values]
    .filter(Boolean)
    .sort((a, b) => a.localeCompare(b, undefined, { numeric: true }))
    .join(", ");
}

export function aggregateVulnerabilities(
  items: ProxyHealthVulnerability[],
  overrides?: ProxyHealthVulnOverride[],
): AggregatedVulnerability[] {
  const omap = overrideMap(overrides);
  const map = new Map<
    string,
    {
      threat_level: number | null;
      problem_code: string;
      problem_url: string;
      group: string;
      artifact: string;
      versions: Set<string>;
      fixed_versions: Set<string>;
      imported_at: string | null;
    }
  >();

  for (const item of items) {
    const key = `${item.problem_code}\0${item.artifact}`;
    let entry = map.get(key);
    if (!entry) {
      entry = {
        threat_level: item.threat_level,
        problem_code: item.problem_code,
        problem_url: item.problem_url,
        group: item.group,
        artifact: item.artifact,
        versions: new Set(),
        fixed_versions: new Set(),
        imported_at: item.imported_at ?? null,
      };
      map.set(key, entry);
    }
    if (item.version) {
      entry.versions.add(item.version);
    }
    if (item.fixed_version) {
      entry.fixed_versions.add(item.fixed_version);
    }
    entry.imported_at = laterImportedAt(entry.imported_at, item.imported_at);
    if (item.threat_level != null) {
      if (entry.threat_level == null || item.threat_level > entry.threat_level) {
        entry.threat_level = item.threat_level;
      }
    }
    if (!entry.problem_url && item.problem_url) {
      entry.problem_url = item.problem_url;
    }
  }

  return [...map.values()]
    .map((entry) => {
      const override = omap.get(
        vulnOverrideKey(entry.problem_code, entry.artifact),
      );
      const fixed_versions = override
        ? override.fixed_version?.trim() || ""
        : sortVersions(entry.fixed_versions);
      return {
        threat_level: entry.threat_level,
        problem_code: entry.problem_code,
        problem_url: entry.problem_url,
        group: entry.group,
        artifact: entry.artifact,
        versions: sortVersions(entry.versions),
        fixed_versions,
        remark: override?.remark?.trim() || "",
        has_override: Boolean(override),
        imported_at: entry.imported_at,
      };
    })
    .sort((a, b) => {
      const ta = formatThreatInteger(a.threat_level) ?? -1;
      const tb = formatThreatInteger(b.threat_level) ?? -1;
      if (tb !== ta) return tb - ta;
      return a.artifact.localeCompare(b.artifact, undefined, {
        sensitivity: "base",
      });
    });
}

export type HealthSortKey = "threat" | "name" | "importedAt";
export type HealthSortDir = "asc" | "desc";

export interface HealthSort {
  key: HealthSortKey;
  dir: HealthSortDir;
}

export const DEFAULT_HEALTH_SORT: HealthSort = { key: "threat", dir: "desc" };

function cmpName(a: string, b: string): number {
  return a.localeCompare(b, undefined, { sensitivity: "base" });
}

function cmpImportedAt(
  a: string | null | undefined,
  b: string | null | undefined,
  dir: HealthSortDir,
): number {
  const left = a?.trim() || "";
  const right = b?.trim() || "";
  if (!left && !right) return 0;
  if (!left) return 1;
  if (!right) return -1;
  const leftMs = Date.parse(left);
  const rightMs = Date.parse(right);
  if (Number.isNaN(leftMs) && Number.isNaN(rightMs)) return 0;
  if (Number.isNaN(leftMs)) return 1;
  if (Number.isNaN(rightMs)) return -1;
  return (leftMs - rightMs) * (dir === "asc" ? 1 : -1);
}

export function nextHealthSort(
  current: HealthSort,
  key: HealthSortKey,
): HealthSort {
  if (current.key === key) {
    return { key, dir: current.dir === "asc" ? "desc" : "asc" };
  }
  return { key, dir: key === "name" ? "asc" : "desc" };
}

export function sortAggregatedVulnerabilities(
  rows: AggregatedVulnerability[],
  sort: HealthSort,
): AggregatedVulnerability[] {
  const dir = sort.dir === "asc" ? 1 : -1;
  return [...rows].sort((a, b) => {
    let cmp = 0;
    if (sort.key === "threat") {
      cmp =
        (formatThreatInteger(a.threat_level) ?? -1) -
        (formatThreatInteger(b.threat_level) ?? -1);
      cmp *= dir;
    } else if (sort.key === "name") {
      cmp = cmpName(a.artifact, b.artifact) * dir;
    } else {
      cmp = cmpImportedAt(a.imported_at, b.imported_at, sort.dir);
    }
    if (cmp !== 0) return cmp;
    const nameCmp = cmpName(a.artifact, b.artifact);
    if (nameCmp !== 0) return nameCmp;
    return (
      (formatThreatInteger(b.threat_level) ?? -1) -
      (formatThreatInteger(a.threat_level) ?? -1)
    );
  });
}

export function sortAggregatedLicenses(
  rows: AggregatedLicense[],
  sort: HealthSort,
): AggregatedLicense[] {
  const dir = sort.dir === "asc" ? 1 : -1;
  return [...rows].sort((a, b) => {
    let cmp = 0;
    if (sort.key === "threat") {
      cmp =
        (licenseThreatRank(a.license_threat) -
          licenseThreatRank(b.license_threat)) *
        dir;
    } else if (sort.key === "name") {
      cmp = cmpName(a.artifact, b.artifact) * dir;
    } else {
      cmp = cmpImportedAt(a.imported_at, b.imported_at, sort.dir);
    }
    if (cmp !== 0) return cmp;
    const nameCmp = cmpName(a.artifact, b.artifact);
    if (nameCmp !== 0) return nameCmp;
    return (
      licenseThreatRank(b.license_threat) - licenseThreatRank(a.license_threat)
    );
  });
}

function blob(parts: Array<string | number | null | undefined>): string {
  return parts
    .map((p) => (p == null ? "" : String(p)))
    .join(" ")
    .toLowerCase();
}

export function filterVulnerabilities(
  items: ProxyHealthVulnerability[],
  query: string,
): ProxyHealthVulnerability[] {
  const q = query.trim().toLowerCase();
  if (!q) return items;
  return items.filter((item) =>
    blob([
      item.group,
      item.artifact,
      item.version,
      item.problem_code,
      item.threat_level,
      formatThreatInteger(item.threat_level),
      item.imported_at,
      formatImportedAt(item.imported_at),
    ]).includes(q),
  );
}

export function filterLicenses(
  items: ProxyHealthLicense[],
  query: string,
): ProxyHealthLicense[] {
  const q = query.trim().toLowerCase();
  if (!q) return items;
  return items.filter((item) =>
    blob([
      item.group,
      item.artifact,
      item.version,
      item.license_threat,
      licenseThreatLabel(item.license_threat),
      item.declared_license,
      item.observed_licenses,
      item.imported_at,
      formatImportedAt(item.imported_at),
    ]).includes(q),
  );
}

export function laterImportedAt(
  a: string | null | undefined,
  b: string | null | undefined,
): string | null {
  const left = a?.trim() || "";
  const right = b?.trim() || "";
  if (!left) return right || null;
  if (!right) return left;
  const leftMs = Date.parse(left);
  const rightMs = Date.parse(right);
  if (Number.isNaN(leftMs)) return right;
  if (Number.isNaN(rightMs)) return left;
  return rightMs > leftMs ? right : left;
}

export function formatImportedAt(iso: string | null | undefined): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleDateString("ko-KR");
}

export function formatReportTime(iso: string | null): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString("ko-KR");
}
