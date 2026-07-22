from pydantic import BaseModel, Field


class Package(BaseModel):
    name: str
    version: str
    format: str
    repository: str


class PackageListResponse(BaseModel):
    items: list[Package] = Field(default_factory=list)
    continuation_token: str | None = None


class TransferRequest(BaseModel):
    name: str
    version: str
    package_type: str = Field(description="pypi | npm | nuget")


class TransferResult(BaseModel):
    pr_url: str | None = None
    pr_number: int | None = None
    state: str = "pending"
    message: str = ""
