import logging

import pytest
from pydantic import SecretStr, ValidationError

from app.core.config import REPO_ROOT, Settings
from app.core.logging import RedactingFilter, redact


def make(**kw) -> Settings:  # type: ignore[no-untyped-def]
    return Settings(_env_file=None, **kw)


def test_defaults_are_safe() -> None:
    s = make()
    assert s.api_host == "127.0.0.1"
    assert s.trading_mode.value == "paper"
    assert s.live_execution_enabled is False


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.10", "::", "example.com"])
def test_non_loopback_bind_rejected(host: str) -> None:
    with pytest.raises(ValidationError):
        make(api_host=host)


@pytest.mark.parametrize("host", ["127.0.0.1", "::1", "localhost"])
def test_loopback_bind_allowed(host: str) -> None:
    assert make(api_host=host).api_host == host


def test_live_execution_fails_closed() -> None:
    with pytest.raises(ValidationError, match="not supported"):
        make(live_execution_enabled=True)


def test_invalid_trading_mode_fails_closed() -> None:
    with pytest.raises(ValidationError):
        make(trading_mode="live")


def test_wildcard_cors_rejected() -> None:
    with pytest.raises(ValidationError):
        make(cors_origins=["*"])


def test_secrets_hidden_from_repr_and_dump() -> None:
    s = make(kalshi_api_key_id=SecretStr("super-secret-id"), fred_api_key="fred-secret")
    assert "super-secret-id" not in repr(s)
    assert "fred-secret" not in repr(s)
    assert "super-secret-id" not in s.model_dump_json()


def test_env_example_loads_with_blank_keys_unset() -> None:
    example = REPO_ROOT / ".env.example"
    s = Settings(_env_file=example)
    assert s.api_host == "127.0.0.1"
    assert s.live_execution_enabled is False
    assert s.cors_origins == ["http://127.0.0.1:5173", "http://localhost:5173"]
    for name in ("kalshi_api_key_id", "kalshi_private_key_path", "fred_api_key", "sec_user_agent"):
        assert getattr(s, name) is None, name


def test_env_file_is_gitignored() -> None:
    ignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".env" in ignore and "!.env.example" in ignore


def test_log_redaction() -> None:
    assert "abc123" not in redact("Authorization: Bearer abc123")
    assert "sig" not in redact("KALSHI-ACCESS-SIGNATURE: sig")
    assert "k" * 10 not in redact("api_key=" + "k" * 10)
    pem = "-----BEGIN PRIVATE KEY-----\nMIIabc\n-----END PRIVATE KEY-----"
    assert "MIIabc" not in redact(f"loaded {pem}")


def test_redacting_filter_applies_to_args() -> None:
    rec = logging.LogRecord("x", logging.INFO, __file__, 1, "token=%s", ("tok-999",), None)
    RedactingFilter().filter(rec)
    assert "tok-999" not in rec.getMessage()
