from pydantic import BaseModel, Field


class Package(BaseModel):
    name: str
    version: str
    format: str
    repository: str


class PackageListResponse(BaseModel):
    items: list[Package] = Field(default_factory=list)
    continuation_token: str | None = None


class PackageMatch(BaseModel):
    name: str
    versions: list[str] = Field(default_factory=list)


class PackageCheckResponse(BaseModel):
    exists: bool
    query: str
    format: str
    repository: str
    packages: list[PackageMatch] = Field(default_factory=list)
    matched_version: str | None = None
    continuation_token: str | None = None


class UserResponse(BaseModel):
    login: str
    name: str | None = None
    avatar_url: str | None = None
    can_request: bool = False
    can_view_orgs: bool = False


class PackageRequestItem(BaseModel):
    name: str
    version: str


class PackageRequestBody(BaseModel):
    packages: list[PackageRequestItem] = Field(min_length=1, max_length=10)


class PackageRequestCheck(BaseModel):
    key: str
    label: str
    passed: bool
    detail: str


class PackageRequestItemValidation(BaseModel):
    name: str
    version: str
    can_request: bool
    checks: list[PackageRequestCheck] = Field(default_factory=list)


class PackageRequestValidation(BaseModel):
    can_request: bool
    items: list[PackageRequestItemValidation] = Field(default_factory=list)


class PackageRequestResult(BaseModel):
    ecosystem: str
    packages: list[PackageRequestItem]
    repository: str
    branch: str
    pr_number: int
    pr_url: str
    pr_state: str
    merged: bool
    automerge: bool
    automerge_detail: str = ""
    requested_by: str


class PackageRequestDeliveryItem(BaseModel):
    name: str
    version: str
    in_hosted: bool = False


class PackageRequestStatus(BaseModel):
    ecosystem: str
    pr_number: int
    pr_url: str
    pr_state: str
    merged: bool
    title: str
    mergeable_state: str = ""
    packages: list[PackageRequestDeliveryItem] = Field(default_factory=list)
    # pending | merged | delivering | done
    delivery: str = "pending"


class ProxyHealthVulnerability(BaseModel):
    threat_level: float | None = None
    problem_code: str
    problem_url: str = ""
    group: str = ""
    artifact: str
    version: str
    imported_at: str | None = None
    published_at: str | None = None
    fixed_version: str | None = None
    in_hosted: bool = False


class ProxyHealthLicense(BaseModel):
    license_threat: str = ""
    declared_license: str = ""
    observed_licenses: str = ""
    group: str = ""
    artifact: str
    version: str
    security_issues: int | None = None
    imported_at: str | None = None
    in_hosted: bool = False


class ProxyHealthVulnOverride(BaseModel):
    problem_code: str
    artifact: str
    fixed_version: str | None = None
    remark: str = ""
    updated_at: str


class ProxyHealthVulnOverrideUpdate(BaseModel):
    problem_code: str
    artifact: str
    fixed_version: str | None = None
    remark: str = ""


class ProxyHealthVulnOverrideKey(BaseModel):
    problem_code: str
    artifact: str


class ProxyHealthResponse(BaseModel):
    ecosystem: str
    repository: str
    generated_at: str | None = None
    fetched_at: str | None = None
    vulnerabilities: list[ProxyHealthVulnerability] = Field(default_factory=list)
    licenses: list[ProxyHealthLicense] = Field(default_factory=list)
    vulnerability_overrides: list[ProxyHealthVulnOverride] = Field(
        default_factory=list
    )


class GhesRepoItem(BaseModel):
    name: str
    managed: bool = False
    present: bool = True


class GhesOrgItem(BaseModel):
    name: str
    managed: bool = False
    present: bool = True
    repos: list[GhesRepoItem] = Field(default_factory=list)


class GhesOrgsResponse(BaseModel):
    synced_at: str | None = None
    organizations: list[GhesOrgItem] = Field(default_factory=list)


class GhesRepoSaveItem(BaseModel):
    name: str
    managed: bool = False


class GhesOrgSaveItem(BaseModel):
    name: str
    managed: bool = False
    repos: list[GhesRepoSaveItem] = Field(default_factory=list)


class GhesOrgsSaveBody(BaseModel):
    organizations: list[GhesOrgSaveItem] = Field(default_factory=list)


class AggregatedPackageRow(BaseModel):
    format: str
    name: str
    version: str
    imported_at: str | None = None
    max_threat_level: float | None = None
    organizations: list[str] = Field(default_factory=list)


class ProjectPackagesListResponse(BaseModel):
    collected_at: str | None = None
    items: list[AggregatedPackageRow] = Field(default_factory=list)


class ProjectPackagesSyncResult(BaseModel):
    collected_at: str | None = None
    org_count: int = 0
    item_count: int = 0
    items: list[AggregatedPackageRow] = Field(default_factory=list)
