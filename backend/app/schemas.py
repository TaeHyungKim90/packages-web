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
