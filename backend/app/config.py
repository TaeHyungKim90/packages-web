from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class EcosystemConfig:
    """package_type → 대상 GitOps 저장소 매핑."""

    def __init__(
        self,
        repo: str,
        requests_file: str,
        ecosystem: str,
        proxy_repo: str,
        inventory_file: str,
    ):
        self.repo = repo
        self.requests_file = requests_file
        self.ecosystem = ecosystem
        self.proxy_repo = proxy_repo
        self.inventory_file = inventory_file


ECOSYSTEM_MAP: dict[str, EcosystemConfig] = {
    "pypi": EcosystemConfig(
        repo="pypiPackages",
        requests_file="requests/pypi_requests_list.yaml",
        ecosystem="pypi",
        proxy_repo="pypi-proxy",
        inventory_file="inventory/pypi_last_list.yaml",
    ),
    "npm": EcosystemConfig(
        repo="npmPackages",
        requests_file="requests/npm_requests_list.yaml",
        ecosystem="npm",
        proxy_repo="npm-proxy",
        inventory_file="inventory/npm_last_list.yaml",
    ),
    "nuget": EcosystemConfig(
        repo="nugetPackages",
        requests_file="requests/nuget_requests_list.yaml",
        ecosystem="nuget",
        proxy_repo="nuget-proxy",
        inventory_file="inventory/nuget_last_list.yaml",
    ),
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    nexus_base_url: str = "https://nexus.sk-inc.com:8081"
    nexus_username: str = ""
    nexus_password: str = ""
    nexus_verify_ssl: bool = True

    github_api_base: str = "https://github.sk-inc.com/api/v3"
    github_token: str = ""
    github_org: str = "CICD"
    github_base_branch: str = "main"
    transfer_auto_merge: bool = True

    cors_origins: list[str] = ["http://localhost:5173"]

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
