"""Custom column types: exact decimals stored as strings and UTC-aware datetimes."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import String
from sqlalchemy.types import TypeDecorator


class DecimalString(TypeDecorator[Decimal]):
    """Stores Decimal as its exact string form (SQLite has no exact decimal type)."""

    impl = String(40)
    cache_ok = True

    def process_bind_param(self, value: Decimal | None, dialect) -> str | None:  # type: ignore[no-untyped-def]
        if value is None:
            return None
        if not isinstance(value, Decimal):
            raise TypeError(f"DecimalString requires Decimal, got {type(value).__name__}")
        if not value.is_finite():
            raise ValueError("Non-finite decimal values are not allowed")
        return str(value)

    def process_result_value(self, value: str | None, dialect) -> Decimal | None:  # type: ignore[no-untyped-def]
        return Decimal(value) if value is not None else None


class UTCDateTime(TypeDecorator[datetime]):
    """Rejects naive datetimes on write; returns timezone-aware UTC on read."""

    impl = String(32)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect) -> str | None:  # type: ignore[no-untyped-def]
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("Naive datetimes are not allowed; use timezone-aware UTC")
        return value.astimezone(UTC).isoformat(timespec="microseconds")

    def process_result_value(self, value: str | None, dialect) -> datetime | None:  # type: ignore[no-untyped-def]
        return datetime.fromisoformat(value).astimezone(UTC) if value is not None else None
