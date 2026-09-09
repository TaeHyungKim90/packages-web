import { describe, expect, it } from "vitest";
import {
  aggregateLicenses,
  aggregateVulnerabilities,
  filterByImportStatus,
  filterLicenses,
  filterVulnerabilities,
  filterVulnerabilitiesByBand,
  formatFixedVersions,
  formatThreatInteger,
  licenseThreatClass,
  licenseThreatLabel,
  matchesThreatBand,
  laterImportedAt,
  nextHealthSort,
  sortAggregatedVulnerabilities,
  sortLicensesByThreat,
  threatSeverity,
} from "./health";

describe("health helpers", () => {
  it("maps CVSS to Nexus-style severity", () => {
    expect(threatSeverity(8.6)).toBe("critical");
    expect(threatSeverity(6.9)).toBe("severe");
    expect(threatSeverity(6.4)).toBe("severe");
    expect(threatSeverity(2.1)).toBe("moderate");
    expect(threatSeverity(null)).toBe("none");
  });

  it("truncates threat level to integer", () => {
    expect(formatThreatInteger(8.6)).toBe(8);
    expect(formatThreatInteger(6.9)).toBe(6);
    expect(formatThreatInteger(6.4)).toBe(6);
    expect(formatThreatInteger(null)).toBeNull();
  });

  it("aggregates same CVE and package with comma-separated versions", () => {
    const rows = aggregateVulnerabilities([
      {
        threat_level: 8.6,
        problem_code: "CVE-2020-1",
        problem_url: "",
        group: "",
        artifact: "foo",
        version: "1.16.3",
      },
      {
        threat_level: 8.6,
        problem_code: "CVE-2020-1",
        problem_url: "",
        group: "",
        artifact: "foo",
        version: "1.16.2",
      },
      {
        threat_level: 9.1,
        problem_code: "CVE-2020-2",
        problem_url: "",
        group: "",
        artifact: "bar",
        version: "2.0.0",
      },
    ]);
    expect(rows).toHaveLength(2);
    expect(rows[0].artifact).toBe("bar");
    expect(formatThreatInteger(rows[0].threat_level)).toBe(9);
    expect(rows[1].artifact).toBe("foo");
    expect(rows[1].versions).toBe("1.16.2, 1.16.3");
  });

  it("aggregates unique fixed versions", () => {
    const rows = aggregateVulnerabilities([
      {
        threat_level: 8.6,
        problem_code: "CVE-2020-1",
        problem_url: "",
        group: "",
        artifact: "foo",
        version: "1.0.0",
        fixed_version: "1.2.0",
      },
      {
        threat_level: 8.6,
        problem_code: "CVE-2020-1",
        problem_url: "",
        group: "",
        artifact: "foo",
        version: "1.1.0",
        fixed_version: "1.2.0",
      },
      {
        threat_level: 8.6,
        problem_code: "CVE-2020-1",
        problem_url: "",
        group: "",
        artifact: "foo",
        version: "0.9.0",
        fixed_version: "1.3.0",
      },
    ]);
    expect(rows).toHaveLength(1);
    expect(rows[0].fixed_versions).toBe("1.2.0, 1.3.0");
  });

  it("keeps the earliest published_at when versions are merged", () => {
    const rows = aggregateVulnerabilities([
      {
        threat_level: 5.0,
        problem_code: "CVE-1",
        problem_url: "",
        group: "",
        artifact: "foo",
        version: "1.0.0",
        published_at: "2026-08-16T00:00:00+00:00",
      },
      {
        threat_level: 5.0,
        problem_code: "CVE-1",
        problem_url: "",
        group: "",
        artifact: "foo",
        version: "1.0.2",
        published_at: "2026-08-18T00:00:00+00:00",
      },
    ]);
    expect(rows).toHaveLength(1);
    expect(rows[0].versions).toBe("1.0.0, 1.0.2");
    expect(rows[0].published_at).toBe("2026-08-16T00:00:00+00:00");
    expect(laterImportedAt(null, "2026-08-18T00:00:00+00:00")).toBe(
      "2026-08-18T00:00:00+00:00",
    );
  });

  it("sorts aggregated vulnerabilities by threat, name, or published date", () => {
    const rows = aggregateVulnerabilities([
      {
        threat_level: 8.1,
        problem_code: "CVE-A",
        problem_url: "",
        group: "",
        artifact: "zeta",
        version: "1.0.0",
        published_at: "2026-08-01T00:00:00+00:00",
      },
      {
        threat_level: 3.2,
        problem_code: "CVE-B",
        problem_url: "",
        group: "",
        artifact: "alpha",
        version: "1.0.0",
        published_at: "2026-08-18T00:00:00+00:00",
      },
      {
        threat_level: 5.0,
        problem_code: "CVE-C",
        problem_url: "",
        group: "",
        artifact: "mid",
        version: "1.0.0",
        published_at: null,
      },
    ]);
    expect(
      sortAggregatedVulnerabilities(rows, { key: "name", dir: "asc" }).map(
        (r) => r.artifact,
      ),
    ).toEqual(["alpha", "mid", "zeta"]);
    expect(
      sortAggregatedVulnerabilities(rows, { key: "threat", dir: "desc" }).map(
        (r) => r.artifact,
      ),
    ).toEqual(["zeta", "mid", "alpha"]);
    expect(
      sortAggregatedVulnerabilities(rows, {
        key: "publishedAt",
        dir: "desc",
      }).map((r) => r.artifact),
    ).toEqual(["alpha", "zeta", "mid"]);
    expect(nextHealthSort({ key: "threat", dir: "desc" }, "threat")).toEqual({
      key: "threat",
      dir: "asc",
    });
    expect(nextHealthSort({ key: "threat", dir: "desc" }, "name")).toEqual({
      key: "name",
      dir: "asc",
    });
  });

  it("labels license threats", () => {
    expect(licenseThreatLabel("WEAKCOPYLEFT")).toBe("약한 카피레프트");
    expect(licenseThreatLabel("LIBERAL")).toBe("허용적");
    expect(licenseThreatLabel("COPYLEFT")).toBe("카피레프트");
    expect(licenseThreatClass("COPYLEFT")).toContain("copyleft");
    expect(licenseThreatClass("LIBERAL")).toContain("liberal");
  });

  it("sorts licenses by Nexus risk order then package name", () => {
    const rows = sortLicensesByThreat([
      {
        license_threat: "LIBERAL",
        declared_license: "MIT",
        observed_licenses: "",
        group: "",
        artifact: "zeta",
        version: "1.0.0",
        security_issues: 0,
      },
      {
        license_threat: "WEAKCOPYLEFT",
        declared_license: "LGPL",
        observed_licenses: "",
        group: "",
        artifact: "mid",
        version: "1.0.0",
        security_issues: 0,
      },
      {
        license_threat: "COPYLEFT",
        declared_license: "GPL",
        observed_licenses: "",
        group: "",
        artifact: "beta",
        version: "1.0.0",
        security_issues: 0,
      },
      {
        license_threat: "COPYLEFT",
        declared_license: "GPL",
        observed_licenses: "",
        group: "",
        artifact: "alpha",
        version: "1.0.0",
        security_issues: 0,
      },
      {
        license_threat: "NON-STANDARD",
        declared_license: "Custom",
        observed_licenses: "",
        group: "",
        artifact: "ns",
        version: "1.0.0",
        security_issues: 0,
      },
      {
        license_threat: "NOT-PROVIDED",
        declared_license: "",
        observed_licenses: "",
        group: "",
        artifact: "np",
        version: "1.0.0",
        security_issues: 0,
      },
    ]);
    expect(rows.map((r) => r.artifact)).toEqual([
      "alpha",
      "beta",
      "ns",
      "np",
      "mid",
      "zeta",
    ]);
  });

  it("aggregates same license package with comma-separated versions", () => {
    const rows = aggregateLicenses([
      {
        license_threat: "LIBERAL",
        declared_license: "MIT",
        observed_licenses: "Not Supported",
        group: "",
        artifact: "requests",
        version: "2.32.3",
        security_issues: 0,
      },
      {
        license_threat: "LIBERAL",
        declared_license: "MIT",
        observed_licenses: "Not Supported",
        group: "",
        artifact: "requests",
        version: "2.32.2",
        security_issues: 1,
      },
      {
        license_threat: "COPYLEFT",
        declared_license: "GPL",
        observed_licenses: "",
        group: "",
        artifact: "gpl-pkg",
        version: "1.0.0",
        security_issues: 0,
      },
    ]);
    expect(rows).toHaveLength(2);
    expect(rows[0].artifact).toBe("gpl-pkg");
    expect(rows[1].artifact).toBe("requests");
    expect(rows[1].versions).toBe("2.32.2, 2.32.3");
    expect(rows[1].security_issues).toBe(1);
  });

  it("filters vulnerabilities by CVE or package name", () => {
    const rows = [
      {
        threat_level: 8.6,
        problem_code: "CVE-2026-16633",
        problem_url: "",
        group: "",
        artifact: "pdfjs-dist",
        version: "5.7.284",
      },
      {
        threat_level: 4.1,
        problem_code: "CVE-2021-23337",
        problem_url: "",
        group: "",
        artifact: "lodash",
        version: "4.17.21",
      },
    ];
    expect(filterVulnerabilities(rows, "lodash")).toHaveLength(1);
    expect(filterVulnerabilities(rows, "CVE-2026")).toHaveLength(1);
    expect(filterVulnerabilities(rows, "")).toHaveLength(2);
    expect(filterVulnerabilities(rows, "8")).toHaveLength(1);
  });

  it("matches threat bands using truncated integer scores", () => {
    expect(matchesThreatBand(6.9, "critical")).toBe(false);
    expect(matchesThreatBand(6.9, "severe")).toBe(true);
    expect(matchesThreatBand(6.4, "severe")).toBe(true);
    expect(matchesThreatBand(3.4, "moderate")).toBe(true);
    expect(matchesThreatBand(8.6, "all")).toBe(true);
    expect(matchesThreatBand(null, "critical")).toBe(false);
    expect(matchesThreatBand(null, "all")).toBe(true);
  });

  it("filters aggregated vulnerabilities by threat band", () => {
    const rows = aggregateVulnerabilities([
      {
        threat_level: 7.1,
        problem_code: "CVE-CRIT",
        problem_url: "",
        group: "",
        artifact: "crit-pkg",
        version: "1.0.0",
      },
      {
        threat_level: 6.9,
        problem_code: "CVE-SEV-69",
        problem_url: "",
        group: "",
        artifact: "aiohttp",
        version: "3.14.1",
      },
      {
        threat_level: 5.2,
        problem_code: "CVE-SEV",
        problem_url: "",
        group: "",
        artifact: "sev-pkg",
        version: "1.0.0",
      },
      {
        threat_level: 2.1,
        problem_code: "CVE-MOD",
        problem_url: "",
        group: "",
        artifact: "mod-pkg",
        version: "1.0.0",
      },
    ]);
    expect(filterVulnerabilitiesByBand(rows, "all")).toHaveLength(4);
    expect(
      filterVulnerabilitiesByBand(rows, "critical").map((r) => r.artifact),
    ).toEqual(["crit-pkg"]);
    expect(
      filterVulnerabilitiesByBand(rows, "severe").map((r) => r.artifact),
    ).toEqual(["aiohttp", "sev-pkg"]);
    expect(
      filterVulnerabilitiesByBand(rows, "moderate").map((r) => r.artifact),
    ).toEqual(["mod-pkg"]);
  });

  it("filters licenses by declared license", () => {
    const rows = [
      {
        license_threat: "LIBERAL",
        declared_license: "MIT",
        observed_licenses: "Not Supported",
        group: "",
        artifact: "postcss-js",
        version: "4.1.0",
        security_issues: 0,
      },
    ];
    expect(filterLicenses(rows, "mit")).toHaveLength(1);
    expect(filterLicenses(rows, "gpl")).toHaveLength(0);
  });

  it("formatFixedVersions shows 미해결 when empty", () => {
    expect(formatFixedVersions("")).toBe("미해결");
    expect(formatFixedVersions("1.2.3")).toBe("1.2.3");
  });

  it("filterByImportStatus filters hosted and pending rows", () => {
    const rows = [
      { artifact: "a", in_hosted: true },
      { artifact: "b", in_hosted: false },
    ];
    expect(filterByImportStatus(rows, "all")).toHaveLength(2);
    expect(filterByImportStatus(rows, "hosted")).toEqual([rows[0]]);
    expect(filterByImportStatus(rows, "pending")).toEqual([rows[1]]);
  });

  it("aggregateVulnerabilities applies manual override per CVE+package", () => {
    const rows = aggregateVulnerabilities(
      [
        {
          threat_level: 5,
          problem_code: "CVE-1",
          problem_url: "",
          group: "",
          artifact: "pkg",
          version: "1.0.0",
          fixed_version: "9.9.9",
        },
      ],
      [
        {
          problem_code: "CVE-1",
          artifact: "pkg",
          fixed_version: "2.0.0",
          remark: "manual",
          updated_at: "2026-01-01T00:00:00+00:00",
        },
      ],
    );
    expect(rows[0].fixed_versions).toBe("2.0.0");
    expect(rows[0].remark).toBe("manual");
    expect(rows[0].has_override).toBe(true);
  });
});
