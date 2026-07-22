export interface Package {
  name: string;
  version: string;
  format: string;
  repository: string;
}

export interface TransferRequest {
  name: string;
  version: string;
  package_type: string;
}

export interface TransferResult {
  pr_url: string | null;
  pr_number: number | null;
  state: string;
  message: string;
}

export type PackageType = "pypi" | "npm" | "nuget";
