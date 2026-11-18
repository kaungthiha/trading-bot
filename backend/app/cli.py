"""Small CLI: `python -m app.cli migrate | downgrade [rev] | seed-mock | ingest [...]`."""

from __future__ import annotations

import argparse
import sys

from alembic import command
from alembic.config import Config

from app.adapters.base import ExchangeMarketDataAdapter
from app.adapters.fixture_market import FixtureMarketAdapter
from app.adapters.kalshi_public import KalshiPublicMarketAdapter
from app.core.clock import SystemClock
from app.core.config import BACKEND_ROOT, MarketDataSource, Settings, get_settings
from app.core.logging import configure_logging
from app.db.session import make_engine, make_session_factory
from app.ingest import IngestionSummary, run_ingestion


def alembic_config(database_url: str | None = None) -> Config:
    cfg = Config(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    if database_url:
        cfg.attributes["database_url"] = database_url
    return cfg


def build_adapter(settings: Settings, source: MarketDataSource) -> ExchangeMarketDataAdapter:
    if source is MarketDataSource.FIXTURE:
        return FixtureMarketAdapter()
    return KalshiPublicMarketAdapter.from_settings(settings, SystemClock())


def ingest(settings: Settings, source: MarketDataSource) -> IngestionSummary:
    engine = make_engine(settings.database_url)
    try:
        adapter = build_adapter(settings, source)
        try:
            return run_ingestion(adapter, make_session_factory(engine), SystemClock())
        finally:
            client = getattr(adapter, "client", None)
            if client is not None:
                client.close()
    finally:
        engine.dispose()


def _print_summary(s: IngestionSummary) -> None:
    print(f"Ingestion {s.status}: adapter={s.adapter} stored={s.count} errors={len(s.errors)}")
    for e in s.errors[:20]:
        print(f"  - {e.scope} [{e.code}] {e.message}")
    if len(s.errors) > 20:
        print(f"  ... {len(s.errors) - 20} more")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="krt")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("migrate", help="Upgrade DB to latest migration")
    down = sub.add_parser("downgrade", help="Downgrade DB")
    down.add_argument("revision", nargs="?", default="-1")
    sub.add_parser("seed-mock", help="Load synthetic MOCK- markets (idempotent)")
    ing = sub.add_parser("ingest", help="Fetch markets from the configured source")
    ing.add_argument("--source", choices=[s.value for s in MarketDataSource])
    ing.add_argument("--series", nargs="+", help="Override KRT_KALSHI_SERIES_WATCHLIST")
    ing.add_argument("--status", help="Override KRT_KALSHI_MARKET_STATUS")
    ing.add_argument("--demo", action="store_true", help="Use the Kalshi demo environment")
    args = parser.parse_args(argv)

    configure_logging()
    settings = get_settings()
    if args.cmd == "migrate":
        command.upgrade(alembic_config(settings.database_url), "head")
    elif args.cmd == "downgrade":
        command.downgrade(alembic_config(settings.database_url), args.revision)
    elif args.cmd == "seed-mock":
        _print_summary(ingest(settings, MarketDataSource.FIXTURE))
    elif args.cmd == "ingest":
        overrides: dict[str, object] = {}
        if args.series:
            overrides["kalshi_series_watchlist"] = args.series
        if args.status:
            overrides["kalshi_market_status"] = args.status
        if args.demo:
            overrides["kalshi_env"] = "demo"
        if overrides:
            # Re-validate so CLI overrides get the same checks as .env values.
            settings = Settings.model_validate({**settings.model_dump(), **overrides})
        source = MarketDataSource(args.source) if args.source else settings.market_data_source
        summary = ingest(settings, source)
        _print_summary(summary)
        return 0 if summary.status in ("success", "partial") else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
