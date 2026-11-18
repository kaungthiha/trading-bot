"""Small CLI: `python -m app.cli migrate|downgrade|seed-mock`."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config

from app.adapters.fixture_market import FixtureMarketAdapter
from app.core.clock import SystemClock
from app.core.config import BACKEND_ROOT, get_settings
from app.db.repositories import MarketRepository
from app.db.session import make_engine, make_session_factory


def alembic_config(database_url: str | None = None) -> Config:
    cfg = Config(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    if database_url:
        cfg.attributes["database_url"] = database_url
    return cfg


def seed_mock(database_url: str) -> int:
    engine = make_engine(database_url)
    factory = make_session_factory(engine)
    adapter = FixtureMarketAdapter()
    with factory() as session:
        repo = MarketRepository(session, SystemClock())
        markets = adapter.list_markets()
        for snap in markets:
            repo.upsert_snapshot(snap, source=adapter.name)
        session.commit()
    engine.dispose()
    return len(markets)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="krt")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("migrate", help="Upgrade DB to latest migration")
    down = sub.add_parser("downgrade", help="Downgrade DB")
    down.add_argument("revision", nargs="?", default="-1")
    sub.add_parser("seed-mock", help="Load synthetic MOCK- markets (idempotent)")
    args = parser.parse_args(argv)

    url = get_settings().database_url
    if args.cmd == "migrate":
        command.upgrade(alembic_config(url), "head")
    elif args.cmd == "downgrade":
        command.downgrade(alembic_config(url), args.revision)
    elif args.cmd == "seed-mock":
        n = seed_mock(url)
        print(f"Seeded {n} mock markets into {Path(url.split('///')[-1]).name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
