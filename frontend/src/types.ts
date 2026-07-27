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
