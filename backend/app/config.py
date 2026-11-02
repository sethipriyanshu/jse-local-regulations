from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration. Every value can be set by an env var of the same name
    (case-insensitive) or in a `.env` file at the repo root."""

    model_config = SettingsConfigDict(
        env_file=(Path(__file__).resolve().parents[2] / ".env"),
        extra="ignore",
    )

    env: str = "local"  # local | dev | prod
    log_level: str = "INFO"

    # SQLAlchemy URL. Local default points at the docker-compose SQL Server.
    database_url: str = "mssql+pymssql://sa:LocalDev_Passw0rd!@127.0.0.1:1433/jse_regs"

    # Blob storage for page snapshots and exports. Default is the Azurite dev account.
    storage_connection_string: str = "UseDevelopmentStorage=true"
    storage_container: str = "regs"

    # Shared passcode for the admin view (MVP stand-in for real login).
    admin_passcode: str = "change-me"
    session_secret: str = "dev-only-secret-change-me"

    # Built frontend served by the API in deployed environments. Unset in local dev,
    # where Vite serves the frontend and proxies /api.
    static_dir: Path | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
