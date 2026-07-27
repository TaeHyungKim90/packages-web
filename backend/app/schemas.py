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
