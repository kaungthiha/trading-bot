"""Typed application configuration.

All settings come from environment variables (prefix ``KRT_``) or a local ``.env`` file
that is never committed. Safety-critical settings fail closed: an invalid or unsafe value
raises at startup instead of silently falling back.
"""

from __future__ import annotations

import ipaddress
from enum import StrEnum
from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_ROOT.parent


class TradingMode(StrEnum):
    PAPER = "paper"


class MarketDataSource(StrEnum):
    FIXTURE = "fixture"
    KALSHI_PUBLIC = "kalshi_public"


class KalshiEnv(StrEnum):
    PRODUCTION = "production"
    DEMO = "demo"


# Documented public REST bases (docs.kalshi.com/getting_started/api_environments, checked
# 2026-11-18). Only these hosts are ever contacted by the read-only adapter.
KALSHI_REST_BASES: dict[KalshiEnv, str] = {
    KalshiEnv.PRODUCTION: "https://external-api.kalshi.com/trade-api/v2",
    KalshiEnv.DEMO: "https://external-api.demo.kalshi.co/trade-api/v2",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="KRT_",
        env_file=(REPO_ROOT / ".env", BACKEND_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: str = "local"

    # --- Network: loopback only -------------------------------------------------------
    api_host: str = "127.0.0.1"
    api_port: int = Field(default=8000, ge=1, le=65535)
    cors_origins: list[str] = ["http://127.0.0.1:5173", "http://localhost:5173"]
    allowed_hosts: list[str] = ["127.0.0.1", "localhost"]

    # --- Storage ----------------------------------------------------------------------
    database_url: str = f"sqlite:///{(BACKEND_ROOT / 'data' / 'krt.sqlite3').as_posix()}"

    # --- Data -------------------------------------------------------------------------
    market_data_source: MarketDataSource = MarketDataSource.FIXTURE
    quote_max_age_seconds: int = Field(default=60, ge=1)

    # --- Kalshi public (unauthenticated) market data ----------------------------------
    kalshi_env: KalshiEnv = KalshiEnv.PRODUCTION
    # Series tickers to ingest, e.g. ["KXCPIYOY","KXFED"]. Empty = nothing is fetched.
    kalshi_series_watchlist: list[str] = []
    kalshi_market_status: str = "open"  # GET /markets?status= filter value
    kalshi_max_pages: int = Field(default=10, ge=1, le=1000)
    kalshi_page_limit: int = Field(default=200, ge=1, le=1000)
    kalshi_orderbook_depth: int = Field(default=10, ge=0, le=100)
    # Unauthenticated limits are not published; stay well below documented tiers.
    kalshi_min_request_interval_seconds: float = Field(default=0.25, ge=0.05)
    kalshi_max_retries: int = Field(default=4, ge=0, le=10)
    http_timeout_seconds: float = Field(default=10.0, gt=0, le=120)

    # --- Evidence sources ------------------------------------------------------------
    # IDs from app/evidence/sources.py registry, e.g. ["fred:CPIAUCSL"]. Only registered
    # sources are accepted (controlled source configuration).
    evidence_sources: list[str] = ["fred:CPIAUCSL"]
    # FRED documents 120 requests/minute; stay under it.
    fred_min_request_interval_seconds: float = Field(default=0.6, ge=0.5)

    # --- Local worker ------------------------------------------------------------------
    worker_kalshi_interval_seconds: int = Field(default=900, ge=60)
    worker_evidence_interval_seconds: int = Field(default=6 * 3600, ge=300)
    # A gap is recorded when a job's last success is older than interval * this factor.
    worker_gap_factor: float = Field(default=2.0, ge=1.1)

    @property
    def kalshi_rest_base(self) -> str:
        return KALSHI_REST_BASES[self.kalshi_env]

    # --- Safety (fail closed) ---------------------------------------------------------
    trading_mode: TradingMode = TradingMode.PAPER
    live_execution_enabled: bool = False

    # --- Credentials: placeholders, NOT used in milestones 01-08 ----------------------
    # Fill these in your local .env only. They are SecretStr so they never appear in
    # repr(), logs, or API responses.
    kalshi_api_key_id: SecretStr | None = None
    kalshi_private_key_path: Path | None = None
    fred_api_key: SecretStr | None = None
    bls_api_key: SecretStr | None = None
    bea_api_key: SecretStr | None = None
    census_api_key: SecretStr | None = None
    sec_user_agent: str | None = None  # SEC asks automated clients to identify themselves
    nyt_api_key: SecretStr | None = None

    @field_validator(
        "kalshi_api_key_id",
        "kalshi_private_key_path",
        "fred_api_key",
        "bls_api_key",
        "bea_api_key",
        "census_api_key",
        "sec_user_agent",
        "nyt_api_key",
        mode="before",
    )
    @classmethod
    def _blank_is_unset(cls, v: object) -> object:
        # `KEY=` placeholders in .env must mean "not configured", not an empty secret.
        if isinstance(v, str) and not v.strip():
            return None
        return v

    @field_validator("kalshi_series_watchlist")
    @classmethod
    def _valid_series(cls, v: list[str]) -> list[str]:
        import re

        for t in v:
            if not re.fullmatch(r"[A-Z0-9][A-Z0-9._-]{0,63}", t):
                raise ValueError(f"Invalid series ticker {t!r}")
        return v

    @field_validator("evidence_sources")
    @classmethod
    def _registered_sources_only(cls, v: list[str]) -> list[str]:
        from app.evidence.sources import SOURCES

        unknown = [s for s in v if s not in SOURCES]
        if unknown:
            raise ValueError(f"Unregistered evidence source(s): {unknown}")
        return v

    @field_validator("kalshi_market_status")
    @classmethod
    def _valid_status_filter(cls, v: str) -> str:
        allowed = {"unopened", "open", "paused", "closed", "settled"}
        if v not in allowed:
            raise ValueError(f"kalshi_market_status must be one of {sorted(allowed)}")
        return v

    @field_validator("api_host")
    @classmethod
    def _host_must_be_loopback(cls, v: str) -> str:
        if v == "localhost":
            return v
        try:
            ip = ipaddress.ip_address(v)
        except ValueError as exc:
            raise ValueError(f"api_host must be a loopback address, got {v!r}") from exc
        if not ip.is_loopback:
            raise ValueError(f"api_host must be a loopback address, got {v!r}")
        return v

    @field_validator("cors_origins")
    @classmethod
    def _no_wildcard_origins(cls, v: list[str]) -> list[str]:
        if any(o.strip() == "*" for o in v):
            raise ValueError("Wildcard CORS origin is not allowed")
        return v

    @field_validator("allowed_hosts")
    @classmethod
    def _no_wildcard_hosts(cls, v: list[str]) -> list[str]:
        if any("*" in h for h in v):
            raise ValueError("Wildcard allowed host is not allowed")
        return v

    @model_validator(mode="after")
    def _live_execution_forbidden(self) -> Settings:
        # No live-execution code exists in milestones 01-08. Refuse to start if someone
        # tries to switch it on rather than pretending the flag does something.
        if self.live_execution_enabled:
            raise ValueError(
                "KRT_LIVE_EXECUTION_ENABLED=true is not supported: live execution is not "
                "implemented and requires a separately authorized milestone."
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
