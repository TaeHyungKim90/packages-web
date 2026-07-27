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

export interface StoredPypiRequest {
  rows: RequestRow[];
  validation: PackageRequestValidation | null;
  result: PackageRequestResult | null;
}
