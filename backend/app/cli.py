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
from app.evidence.ingest import build_evidence_adapter, run_evidence_ingestion
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
    ev = sub.add_parser("ingest-evidence", help="Fetch evidence (e.g. FRED vintages)")
    ev.add_argument(
        "--source", nargs="+", help="Source ids (default: KRT_EVIDENCE_SOURCES), e.g. fred:CPIAUCSL"
    )
    sub.add_parser("worker", help="Run the scheduled collector (Ctrl+C to stop)")
    sub.add_parser("evaluate-models", help="Walk-forward evaluate all models; store reports")
    fc = sub.add_parser("forecast-cpi", help="Forecast next CPI MoM first print > threshold")
    fc.add_argument("--threshold", default="0.3", help="Percent, on the 0.1 grid (default 0.3)")
    fc.add_argument("--save", action="store_true", help="Store forecasts as immutable model runs")
    sub.add_parser("propose-mappings", help="Propose market->contract mappings (KXCPI)")
    sub.add_parser("list-mappings", help="Show latest mapping per market with review notes")
    cm = sub.add_parser("confirm-mapping", help="Confirm a proposed mapping after reading rules")
    cm.add_argument("ticker")
    cm.add_argument("--yes", action="store_true", help="Required: you reviewed the rules")
    cm.add_argument("--note", help="Optional review note")
    rm = sub.add_parser("reject-mapping", help="Reject a mapping")
    rm.add_argument("ticker")
    rm.add_argument("--note")
    sub.add_parser("generate-signals", help="Evaluate mapped markets; store research signals")
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
    elif args.cmd == "ingest-evidence":
        if args.source:
            settings = Settings.model_validate(
                {**settings.model_dump(), "evidence_sources": args.source}
            )
        ok = True
        for sid in settings.evidence_sources:
            summary = ingest_evidence(settings, sid)
            _print_summary(summary)
            ok = ok and summary.status in ("success", "partial")
        return 0 if ok else 1
    elif args.cmd == "worker":
        from app.worker import main as worker_main

        return worker_main()
    elif args.cmd in ("evaluate-models", "forecast-cpi"):
        return _research_cmd(args, settings)
    elif args.cmd in ("propose-mappings", "list-mappings", "confirm-mapping", "reject-mapping",
                      "generate-signals"):
        return _signal_cmd(args, settings)
    return 0


def _signal_cmd(args: argparse.Namespace, settings: Settings) -> int:
    import json

    from sqlalchemy import select

    from app.db.models import Market, MarketMapping
    from app.signals.mapping import MappingError, current_rules, decide, latest_mapping, propose_all
    from app.signals.service import generate_signals

    engine = make_engine(settings.database_url)
    now = SystemClock().now()
    try:
        with make_session_factory(engine)() as s:
            if args.cmd == "propose-mappings":
                created = propose_all(s, now)
                s.commit()
                for m, row in created:
                    print(f"{row.status:9} {m.external_ticker}")
                print(f"{len(created)} new proposal(s). Review with list-mappings, then "
                      "confirm-mapping <TICKER> --yes")
                return 0
            if args.cmd == "list-mappings":
                for mid in s.scalars(select(MarketMapping.market_id).distinct()).all():
                    m = s.get(Market, mid)
                    mp = latest_mapping(s, mid)
                    rules = current_rules(s, mid)
                    stale = "" if rules and rules.hash == mp.rules_hash else " [RULES CHANGED]"
                    print(f"{mp.status:9} {m.external_ticker}  month={mp.reference_month} "
                          f"threshold={mp.threshold}{stale}")
                    for n in json.loads(mp.notes_json):
                        print(f"           - {n}")
                return 0
            if args.cmd == "generate-signals":
                sigs = generate_signals(s, settings, now)
                s.commit()
                for g in sigs:
                    m = s.get(Market, g.market_id)
                    edge = f" lower_edge={g.lower_edge}" if g.lower_edge is not None else ""
                    print(f"{g.decision:13} {m.external_ticker}{edge}  "
                          f"{', '.join(json.loads(g.reasons_json))}")
                print("Research signals only: nothing was ordered or authorized.")
                return 0
            market = s.scalar(select(Market).where(Market.external_ticker == args.ticker))
            if market is None:
                print(f"Unknown market {args.ticker}")
                return 1
            if args.cmd == "confirm-mapping":
                rules = current_rules(s, market.id)
                mp = latest_mapping(s, market.id)
                print(f"Market: {market.external_ticker}")
                print("Rules:\n" + (rules.rules_text if rules else "-"))
                if mp:
                    print("Review notes:")
                    for n in json.loads(mp.notes_json):
                        print(f"  - {n}")
                if not args.yes:
                    print("\nNot confirmed. Re-run with --yes once you have reviewed the rules "
                          "and contract terms.")
                    return 2
            try:
                row = decide(s, market, now, confirm=args.cmd == "confirm-mapping",
                             note=args.note)
            except MappingError as e:
                print(f"Error: {e}")
                return 1
            s.commit()
            print(f"{row.status}: {market.external_ticker}")
            return 0
    finally:
        engine.dispose()


def _research_cmd(args: argparse.Namespace, settings: Settings) -> int:
    from decimal import Decimal, InvalidOperation

    from app.research.service import evaluate_and_save, forecast_all, save_forecast

    engine = make_engine(settings.database_url)
    clock = SystemClock()
    try:
        with make_session_factory(engine)() as s:
            if args.cmd == "evaluate-models":
                for rep in evaluate_and_save(s, clock.now()):
                    print(f"{rep.model} v{rep.version} dataset={rep.dataset_hash[:12]}")
                    for label, m in (("dev", rep.dev), ("holdout", rep.holdout)):
                        if m.brier is None:
                            print(f"  {label:8} no scored predictions")
                            continue
                        print(f"  {label:8} predictions={m.n_predictions} months={m.n_events} "
                              f"abstained={m.n_abstained} base_rate={m.base_rate:.3f} "
                              f"brier={m.brier:.4f} log_loss={m.log_loss:.4f}")
                s.commit()
                return 0
            try:
                threshold = Decimal(args.threshold)
            except InvalidOperation:
                print("--threshold must be a number like 0.3")
                return 2
            contract, forecasts, _ = forecast_all(s, threshold, clock.now())
            if contract is None:
                print("No CPI evidence stored; run: python -m app.cli ingest-evidence")
                return 1
            print(f"Contract: {contract.key}")
            for f in forecasts:
                if f.p_yes is None:
                    print(f"  {f.model:18} ABSTAIN {', '.join(f.reasons)}")
                else:
                    print(f"  {f.model:18} p={f.p_yes:.3f} band=[{f.lower:.3f}, {f.upper:.3f}]")
                if args.save:
                    save_forecast(s, f, clock.now())
            if args.save:
                s.commit()
                print("Saved as model runs.")
            print("Note: estimates from past CPI prints only; not trade recommendations.")
            return 0
    finally:
        engine.dispose()


def ingest_evidence(settings: Settings, source_id: str) -> IngestionSummary:
    from app.adapters.base import AdapterError, FetchError

    engine = make_engine(settings.database_url)
    clock = SystemClock()
    try:
        try:
            adapter = build_evidence_adapter(source_id, settings, clock)
        except AdapterError as e:  # e.g. missing API key: report without a network call
            return IngestionSummary("-", source_id, "failed", 0,
                                    [FetchError(f"adapter:{source_id}", e.code, str(e))])
        try:
            return run_evidence_ingestion(adapter, make_session_factory(engine), clock)
        finally:
            adapter.client.close()  # type: ignore[attr-defined]
    finally:
        engine.dispose()


if __name__ == "__main__":
    sys.exit(main())
