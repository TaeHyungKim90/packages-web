export interface PackageMatch {
  name: string;
  versions: string[];
}

export interface PackageCheckResponse {
  exists: boolean;
  query: string;
  format: string;
  repository: string;
  packages: PackageMatch[];
  matched_version: string | null;
  continuation_token: string | null;
}

export type PackageType = "pypi" | "npm" | "nuget";

export interface CheckParams {
  format: PackageType;
  name: string;
  version?: string;
  continuationToken?: string;
}

export interface AuthUser {
  login: string;
  name: string | null;
  avatar_url: string | null;
  can_request: boolean;
  can_view_orgs: boolean;
}

export interface PackageRequestItem {
  name: string;
  version: string;
}

export type DeliveryStatus = "pending" | "merged" | "delivering" | "done";

export interface PackageRequestResult {
  ecosystem: string;
  packages: PackageRequestItem[];
  repository: string;
  branch: string;
  pr_number: number;
  pr_url: string;
  pr_state: string;
  merged: boolean;
  automerge: boolean;
  automerge_detail?: string;
  requested_by: string;
  delivery?: DeliveryStatus;
}

export interface PackageRequestCheck {
  key: string;
  label: string;
  passed: boolean;
  detail: string;
}

export interface PackageRequestItemValidation {
  name: string;
  version: string;
  can_request: boolean;
  checks: PackageRequestCheck[];
}

export interface PackageRequestValidation {
  can_request: boolean;
  items: PackageRequestItemValidation[];
}

export interface PackageRequestDeliveryItem {
  name: string;
  version: string;
  in_hosted: boolean;
}

export interface PackageRequestStatus {
  ecosystem: string;
  pr_number: number;
  pr_url: string;
  pr_state: string;
  merged: boolean;
  title: string;
  mergeable_state?: string;
  packages: PackageRequestDeliveryItem[];
  delivery: DeliveryStatus;
}

export interface RequestRow {
  id: string;
  name: string;
  version: string;
}

export interface StoredPackageRequest {
  rows: RequestRow[];
  validation: PackageRequestValidation | null;
  result: PackageRequestResult | null;
}

/** @deprecated Use StoredPackageRequest */
export type StoredPypiRequest = StoredPackageRequest;

export type ProxyHealthView = "vulnerabilities" | "licenses";

export interface ProxyHealthVulnerability {
  threat_level: number | null;
  problem_code: string;
  problem_url: string;
  group: string;
  artifact: string;
  version: string;
  imported_at?: string | null;
  published_at?: string | null;
  fixed_version?: string | null;
  in_hosted?: boolean;
  /** 정상버전·오탐 — 리스트 표시, 엑셀 제외 */
  resolved?: boolean;
}

export interface ProxyHealthLicense {
  license_threat: string;
  declared_license: string;
  observed_licenses: string;
  group: string;
  artifact: string;
  version: string;
  security_issues: number | null;
  imported_at?: string | null;
  in_hosted?: boolean;
}

export interface ProxyHealthVulnOverride {
  problem_code: string;
  artifact: string;
  fixed_version: string | null;
  remark: string;
  updated_at: string;
}

export interface ProxyHealthVulnOverrideUpdate {
  problem_code: string;
  artifact: string;
  fixed_version?: string | null;
  remark?: string;
}

export interface ProxyHealthResponse {
  ecosystem: string;
  repository: string;
  generated_at: string | null;
  fetched_at?: string | null;
  vulnerabilities: ProxyHealthVulnerability[];
  licenses: ProxyHealthLicense[];
  vulnerability_overrides?: ProxyHealthVulnOverride[];
}

export interface GhesRepoItem {
  name: string;
  managed: boolean;
  present: boolean;
}

export interface GhesOrgItem {
  name: string;
  managed: boolean;
  present: boolean;
  repos: GhesRepoItem[];
}

export interface GhesOrgsResponse {
  synced_at: string | null;
  organizations: GhesOrgItem[];
}

export interface GhesMemberItem {
  login: string;
  name?: string | null;
  email?: string | null;
  user_type: string;
  site_admin: boolean;
  organizations: string[];
  organizations_label: string;
}

export interface GhesMembersResponse {
  synced_at: string | null;
  members: GhesMemberItem[];
}

export interface AggregatedPackageRow {
  format: "pypi" | "npm" | "nuget" | string;
  name: string;
  version: string;
  imported_at: string | null;
  max_threat_level: number | null;
  organizations: string[];
}

export interface ProjectPackagesListResponse {
  collected_at: string | null;
  items: AggregatedPackageRow[];
}

export interface ProjectPackagesSyncResult {
  collected_at: string | null;
  org_count: number;
  item_count: number;
  items: AggregatedPackageRow[];
}

