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

    # Blob storage for page snapshots and exports. An Azure connection string, or
    # "file:<dir>" (relative to the repo root) for a local folder.
    storage_connection_string: str = "file:.data/blobs"
    storage_container: str = "regs"

    # Azure AI Foundry / Azure OpenAI. The deployment is swappable (PLAN.md D5).
    azure_openai_endpoint: str = ""
    azure_openai_api_key: str = ""
    azure_openai_deployment: str = ""
    azure_openai_api_version: str = "2024-10-21"
    # USD per 1M tokens for cost tracking; defaults are gpt-4.1-mini list prices.
    llm_price_in_per_m: float = 0.40
    llm_price_out_per_m: float = 1.60

    # Fetcher etiquette.
    fetch_user_agent: str = (
        "JSE-RegsBot/0.1 (internal regulations tracker; Jordan & Skala Engineers)"
    )
    fetch_timeout_s: float = 30.0
    fetch_max_bytes: int = 25_000_000
    fetch_min_interval_s: float = 2.0  # per domain

    # Shared passcode for the admin view (MVP stand-in for real login).
    admin_passcode: str = "change-me"
    session_secret: str = "dev-only-secret-change-me"

    # Built frontend served by the API in deployed environments. Unset in local dev,
    # where Vite serves the frontend and proxies /api.
    static_dir: Path | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
