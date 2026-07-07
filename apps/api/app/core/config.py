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
    # Domestic A-share sources (FRA-23). AkShare is token-less; Tushare Pro
    # requires a registered token from https://tushare.pro (points-tiered).
    tushare_token: str = Field(default="", alias="TUSHARE_TOKEN")

    # Data quality
    quality_large_return_threshold: float = Field(
        default=0.2, alias="QUALITY_LARGE_RETURN_THRESHOLD"
    )

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

    # Sentiment / News (FRA-67). The news provider key selects an adapter from
    # the sentiment/providers registry; "fixture" ships sample data so tests and
    # the Week-4 demo never touch the network. Limits guard against runaway
    # fetches from the volatile text sources this milestone warned about.
    news_provider: str = Field(default="fixture", alias="NEWS_PROVIDER")
    news_fetch_timeout_seconds: int = Field(default=30, alias="NEWS_FETCH_TIMEOUT_SECONDS")
    news_max_items_per_asset: int = Field(default=100, alias="NEWS_MAX_ITEMS_PER_ASSET")
    news_sync_max_window_days: int = Field(default=30, alias="NEWS_SYNC_MAX_WINDOW_DAYS")

    # Sentiment classifier (FRA-68). Selects the classifier adapter; "fixture"
    # is a deterministic keyword-rule classifier (default, no LLM/network, so
    # tests/demo stay offline and reproducible). "openai" calls an
    # OpenAI-compatible chat completions endpoint via httpx and requires
    # OPENAI_API_KEY — gated by this switch so the default path needs no key.
    sentiment_classifier: str = Field(default="fixture", alias="SENTIMENT_CLASSIFIER")
    sentiment_temperature: float = Field(default=0.0, alias="SENTIMENT_TEMPERATURE")
    sentiment_classify_batch_size: int = Field(default=10, alias="SENTIMENT_CLASSIFY_BATCH_SIZE")
    sentiment_classify_max_items: int = Field(default=200, alias="SENTIMENT_CLASSIFY_MAX_ITEMS")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached Settings instance."""
    return Settings()


settings = get_settings()
