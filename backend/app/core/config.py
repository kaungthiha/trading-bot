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
