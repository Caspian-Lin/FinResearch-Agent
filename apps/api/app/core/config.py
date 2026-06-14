"""Application configuration loaded from environment variables.

Uses Pydantic Settings for typed config. Reads from `.env` if present,
otherwise from process environment.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed application settings.

    All values have sensible defaults for local development. Production
    deployments must override secrets via environment variables.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # App
    app_name: str = "FinResearch Agent"
    debug: bool = Field(default=False, alias="DEBUG")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    log_format: str = Field(default="json", alias="LOG_FORMAT")

    # API server
    api_host: str = Field(default="0.0.0.0", alias="API_HOST")
    api_port: int = Field(default=8000, alias="API_PORT")
    api_workers: int = Field(default=1, alias="API_WORKERS")
    cors_origins: str = Field(
        default="http://localhost:5173,http://localhost:3000",
        alias="CORS_ORIGINS",
    )

    # Database
    database_url: str = Field(
        default="postgresql+psycopg://finresearch:finresearch_dev_password@postgres:5432/finresearch",
        alias="DATABASE_URL",
    )
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_echo: bool = False

    # Redis
    redis_url: str = Field(
        default="redis://redis:6379/0",
        alias="REDIS_URL",
    )

    # Auth
    jwt_secret: str = Field(default="change_me", alias="JWT_SECRET")
    jwt_algorithm: str = Field(default="HS256", alias="JWT_ALGORITHM")
    jwt_expire_minutes: int = Field(default=1440, alias="JWT_EXPIRE_MINUTES")

    # Initial admin
    initial_admin_email: str = Field(
        default="admin@finresearch.local",
        alias="INITIAL_ADMIN_EMAIL",
    )
    initial_admin_password: str = Field(
        default="admin_password_change_me",
        alias="INITIAL_ADMIN_PASSWORD",
    )

    # Data sources
    yfinance_user_agent: str = Field(
        default="FinResearch-Agent/0.1",
        alias="YFINANCE_USER_AGENT",
    )
    polygon_api_key: str = Field(default="", alias="POLYGON_API_KEY")
    alpha_vantage_api_key: str = Field(default="", alias="ALPHA_VANTAGE_API_KEY")
    fred_api_key: str = Field(default="", alias="FRED_API_KEY")

    # LLM
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    openai_base_url: str = Field(
        default="https://api.openai.com/v1",
        alias="OPENAI_BASE_URL",
    )
    openai_model: str = Field(default="gpt-4o-mini", alias="OPENAI_MODEL")
    llm_request_timeout_seconds: int = Field(
        default=60,
        alias="LLM_REQUEST_TIMEOUT_SECONDS",
    )

    # Worker queues
    rq_queue_default: str = Field(default="default", alias="RQ_QUEUE_DEFAULT")
    rq_queue_data: str = Field(default="data_sync", alias="RQ_QUEUE_DATA")
    rq_queue_backtest: str = Field(default="backtest", alias="RQ_QUEUE_BACKTEST")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached Settings instance."""
    return Settings()


settings = get_settings()
