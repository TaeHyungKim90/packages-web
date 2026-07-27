from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class EcosystemConfig:
    """package_type → Nexus hosted + GitOps repo 매핑."""

    def __init__(
        self,
        *,
        ecosystem: str,
        hosted_repo: str,
        proxy_repo: str,
        gitops_repo: str,
        requests_file: str,
        inventory_file: str,
    ):
        self.ecosystem = ecosystem
        self.hosted_repo = hosted_repo
        self.proxy_repo = proxy_repo
        self.gitops_repo = gitops_repo
        self.requests_file = requests_file
        self.inventory_file = inventory_file


ECOSYSTEM_MAP: dict[str, EcosystemConfig] = {
    "pypi": EcosystemConfig(
        ecosystem="pypi",
        hosted_repo="pypi-hosted",
        proxy_repo="pypi-proxy",
        gitops_repo="pypiPackages",
        requests_file="requests/pypi_requests_list.yaml",
        inventory_file="inventory/pypi_last_list.yaml",
    ),
    "npm": EcosystemConfig(
        ecosystem="npm",
        hosted_repo="npm-hosted",
        proxy_repo="npm-proxy",
        gitops_repo="npmPackages",
        requests_file="requests/npm_requests_list.yaml",
        inventory_file="inventory/npm_last_list.yaml",
    ),
    "nuget": EcosystemConfig(
        ecosystem="nuget",
        hosted_repo="nuget-hosted",
        proxy_repo="nuget-proxy",
        gitops_repo="nugetPackages",
        requests_file="requests/nuget_requests_list.yaml",
        inventory_file="inventory/nuget_last_list.yaml",
    ),
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    nexus_base_url: str = "https://nexus.sk-inc.com:8081"
    nexus_username: str = ""
    nexus_password: str = ""
    nexus_verify_ssl: bool = True
    # Public registry bases for "does this version exist?" (not Nexus proxy cache)
    pypi_json_base_url: str = "https://pypi.org"
    npm_registry_base_url: str = "https://registry.npmjs.org"

    cors_origins: Annotated[list[str], NoDecode] = Field(
        default=["http://localhost:5173", "http://127.0.0.1:5173"]
    )

    github_base_url: str = "https://github.sk-inc.com"
    github_api_base: str = "https://github.sk-inc.com/api/v3"
    github_oauth_client_id: str = ""
    github_oauth_client_secret: str = ""
    oauth_redirect_uri: str = "http://localhost:5173/api/auth/callback"
    frontend_base_url: str = "http://localhost:5173"

    session_secret: str = "change-me-to-a-long-random-string"
    session_cookie_name: str = "packages_web_session"
    session_max_age_seconds: int = 86400
    session_cookie_secure: bool = False

    github_token: str = ""
    github_org: str = "CICD"
    github_base_branch: str = "main"
    transfer_auto_merge: bool = True

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: str | list[str]) -> list[str]:
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        return v

    def get_ecosystem(self, package_type: str) -> EcosystemConfig:
        key = package_type.lower()
        if key not in ECOSYSTEM_MAP:
            raise ValueError(f"Unsupported package type: {package_type}")
        return ECOSYSTEM_MAP[key]


settings = Settings()
