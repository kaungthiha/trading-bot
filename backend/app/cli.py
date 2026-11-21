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


def _research_eval(settings: Settings) -> int:
    """Offline: reads stored investigations and the catalog's game times. No network."""
    import json as _json

    from sqlalchemy import select

    from app.db.models import CatalogEvent, Investigation
    from app.db.session import make_engine, make_session_factory
    from app.investigate import schemas as S
    from app.investigate.evaluate import evaluate

    engine = make_engine(settings.database_url)
    with make_session_factory(engine)() as s:
        rows = s.scalars(select(Investigation)).all()
        results = [S.Result.model_validate(_json.loads(r.result_json)) for r in rows]
        events = {r.hypothesis.event_ticker for r in results}
        starts = {e.event_ticker: e.occurs_at for e in s.scalars(
            select(CatalogEvent).where(CatalogEvent.event_ticker.in_(events))) if e.occurs_at}
    engine.dispose()
    print(_json.dumps(evaluate(results, starts=starts).rates(), indent=2))
    return 0


def _research_smoke(settings: Settings, live_moneypuck: bool) -> int:
    """Live checks run only with an explicit flag, and only against free, non-billed sources
    the registry permits. Brave is never called here."""
    if not live_moneypuck:
        print("Nothing run. Pass --live-moneypuck to download MoneyPuck's two listed season "
              "CSVs once (free, non-billed, credited). Brave is never called by this command.")
        return 0
    from datetime import UTC, datetime

    from app.sportsdata.moneypuck import MoneyPuck, season_of

    src = MoneyPuck(settings)
    try:
        d = src.season(season_of(datetime.now(UTC)))
    finally:
        src.close()
    print(f"MoneyPuck {d.season}: {len(d.teams)} teams, "
          f"{sum(len(v) for v in d.goalies.values())} goalies, data as of {d.data_as_of} "
          "(Data: MoneyPuck.com)")
    return 0 if len(d.teams) >= 30 else 1


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
    po = sub.add_parser("paper-order", help="Simulate an IOC limit order (no exchange contact)")
    po.add_argument("ticker")
    po.add_argument("side", choices=["YES", "NO"])
    po.add_argument("action", choices=["BUY", "SELL"])
    po.add_argument("quantity", type=int)
    po.add_argument("limit_price")
    po.add_argument("--scenario", choices=["conservative", "baseline", "harsh"])
    sub.add_parser("paper-account", help="Cash, positions, realized/unrealized P&L")
    sub.add_parser("paper-settle", help="Refresh held markets; settle finalized ones")
    pr = sub.add_parser("paper-replay", help="Replay stored candidate signals (simulation)")
    pr.add_argument("--scenario", choices=["conservative", "baseline", "harsh"])
    sub.add_parser("backup", help="Back up the database to backend/data/backups/")
    sub.add_parser("list-backups", help="List available backups")
    rs = sub.add_parser("restore", help="Restore a backup (current data is backed up first)")
    rs.add_argument("file")
    rs.add_argument("--yes", action="store_true")
    rz = sub.add_parser("reset", help="Back up, then start with an empty database")
    rz.add_argument("--yes", action="store_true")
    sub.add_parser("demo", help="Build the offline demo database (synthetic data)")
    sp = sub.add_parser("set-approval-pin", help="Create the PIN hash required to approve orders")
    sp.add_argument("--write-env", action="store_true",
                    help="Write KRT_EXECUTION_APPROVAL_PIN_HASH into the repo's .env")
    sub.add_parser("execution-status", help="Show execution mode, kill switch and caps")
    ks = sub.add_parser("kill-switch", help="Engage or release the execution kill switch")
    ks.add_argument("action", choices=["engage", "release"])
    ks.add_argument("--reason", default="")
    ks.add_argument("--yes", action="store_true", help="Required to release")
    er = sub.add_parser("execution-reconcile", help="Read-only lookup for an UNKNOWN intent")
    er.add_argument("intent_id")
    sub.add_parser("scan", help="Scan all open Kalshi events for mispricings (public data)")
    sub.add_parser("journal-settle", help="Settle journaled trades on finalized Kalshi results")
    sub.add_parser("scorecard", help="Real-money scorecard of executed thesis cards")
    sub.add_parser("research-eval",
                   help="Evidence-quality report over stored investigations (offline, free)")
    smk = sub.add_parser("research-smoke",
                         help="Opt-in live check of free, non-billed data sources (never Brave)")
    smk.add_argument("--live-moneypuck", action="store_true",
                     help="Download MoneyPuck's two listed season CSVs once and summarise them")
    args = parser.parse_args(argv)

    configure_logging()
    settings = get_settings()
    if args.cmd == "research-eval":
        return _research_eval(settings)
    if args.cmd == "research-smoke":
        return _research_smoke(settings, args.live_moneypuck)
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
    elif args.cmd.startswith("paper-"):
        return _paper_cmd(args, settings)
    elif args.cmd in ("backup", "list-backups", "restore", "reset", "demo"):
        return _ops_cmd(args, settings)
    elif args.cmd in ("set-approval-pin", "execution-status", "kill-switch",
                      "execution-reconcile"):
        return _execution_cmd(args, settings)
    elif args.cmd in ("scan", "journal-settle", "scorecard"):
        return _scanner_cmd(args, settings)
    return 0


def _scanner_cmd(args: argparse.Namespace, settings: Settings) -> int:
    import json

    from sqlalchemy import select

    from app.adapters.kalshi_public import KalshiPublicClient
    from app.db.models import JournalEntry
    from app.db.models import Opportunity as OppRow
    from app.scanner.service import run_scan, scorecard, settle_journal

    engine = make_engine(settings.database_url)
    clock = SystemClock()
    factory = make_session_factory(engine)
    try:
        if args.cmd == "scan":
            with KalshiPublicClient.from_settings(settings) as client:
                r = run_scan(factory, settings, client, clock)
            print(f"Scan {r.status}: {r.events} events / {r.markets} markets, "
                  f"{r.candidates} candidates, {r.confirmed} confirmed, "
                  f"{len(r.new_cards)} new card(s)")
            if r.budget_note:
                print(f"Budget: {r.budget_note}")
            with factory() as s:
                for cid in r.new_cards:
                    o = s.get(OppRow, cid)
                    tag = "GUARANTEED" if o.guaranteed else "CONDITIONAL"
                    print(f"  [{tag}] {o.title}: cost ${o.cost} -> min ${o.min_payoff} "
                          f"(profit ${o.profit}); review it in the UI")
            print("Suggestions only: verify each card, then trade on Kalshi yourself.")
            return 0 if r.status != "failed" else 1
        with factory() as s:
            if args.cmd == "journal-settle":
                tickers = sorted({lg["ticker"] for e in s.scalars(select(JournalEntry).where(
                    JournalEntry.action == "EXECUTED")) for lg in json.loads(e.legs_json)})
                results: dict[str, str] = {}
                with KalshiPublicClient.from_settings(settings) as client:
                    for i in range(0, len(tickers), 50):
                        body = client.get("/markets", {"tickers": ",".join(tickers[i:i + 50])})
                        for m in body.get("markets") or []:
                            if m.get("status") == "finalized" and m.get("result") in ("yes", "no"):
                                results[m["ticker"]] = m["result"]
                done = settle_journal(s, results, clock.now())
                s.commit()
                print(f"Settled {len(done)} trade(s); {len(results)}/{len(tickers)} legs final.")
                return 0
            card = scorecard(s, settings)
            print(f"Budget ${card['budget']} | available ${card['available']} | open "
                  f"${card['open_cost']} | realized P&L ${card['realized_pnl']}")
            for k in ("guaranteed", "conditional"):
                c = card[k]
                print(f"  {k:11} executed {c['executed']} settled {c['settled']} "
                      f"wins {c['wins']} P&L ${c['pnl']}")
            return 0
    finally:
        engine.dispose()


def _execution_cmd(args: argparse.Namespace, settings: Settings) -> int:
    import getpass
    import re

    from app.core.config import REPO_ROOT
    from app.execution.service import (
        ExecutionError,
        hash_pin,
        kill_switch_engaged,
        reconcile,
        set_kill_switch,
    )

    if args.cmd == "set-approval-pin":
        pin = getpass.getpass("New approval PIN (min 6 chars, not echoed): ")
        if pin != getpass.getpass("Repeat PIN: "):
            print("PINs do not match.")
            return 1
        try:
            line = f"KRT_EXECUTION_APPROVAL_PIN_HASH={hash_pin(pin)}"
        except ValueError as e:
            print(e)
            return 1
        if args.write_env:
            env = REPO_ROOT / ".env"
            text = env.read_text(encoding="utf-8") if env.exists() else ""
            if re.search(r"^KRT_EXECUTION_APPROVAL_PIN_HASH=.*$", text, flags=re.M):
                text = re.sub(r"^KRT_EXECUTION_APPROVAL_PIN_HASH=.*$", line, text, flags=re.M)
            else:
                text = text.rstrip("\n") + ("\n" if text else "") + line + "\n"
            env.write_text(text, encoding="utf-8")
            print("Saved the PIN hash to .env (the PIN itself is not stored). Restart the backend.")
        else:
            print("Add this line to your .env (it is a salted hash, not the PIN):")
            print(line)
        return 0

    engine = make_engine(settings.database_url)
    clock = SystemClock()
    try:
        with make_session_factory(engine)() as s:
            if args.cmd == "execution-status":
                print(f"execution_enabled={settings.execution_enabled} "
                      f"env={settings.execution_env.value} production=not implemented")
                print(f"kill_switch={'ENGAGED' if kill_switch_engaged(s) else 'released'} "
                      f"pin_configured={settings.execution_approval_pin_hash is not None}")
                print(f"caps: {settings.execution_max_contracts_per_order} contracts/order, "
                      f"${settings.execution_max_cost_per_order}/order, "
                      f"{settings.execution_max_position_contracts} contracts/position, "
                      f"${settings.execution_max_daily_cost}/day")
                return 0
            if args.cmd == "kill-switch":
                if args.action == "release" and not args.yes:
                    print("Releasing allows approved orders to be SENT to the "
                          f"{settings.execution_env.value.upper()} environment. Re-run with "
                          "--yes to confirm.")
                    return 2
                set_kill_switch(s, clock.now(), engage=args.action == "engage", actor="cli",
                                reason=args.reason)
                s.commit()
                print(f"Kill switch {'ENGAGED' if args.action == 'engage' else 'released'}.")
                return 0
            if args.cmd == "execution-reconcile":
                from app.execution.factory import build_gateway

                try:
                    gw = build_gateway(settings, s, None)
                    intent = reconcile(s, args.intent_id, gw, clock.now())
                except ExecutionError as e:
                    print(f"Error: {e.code} {e.message}")
                    return 1
                print(f"{intent.id}: {intent.status}")
                return 0
    finally:
        engine.dispose()
    return 0


def _ops_cmd(args: argparse.Namespace, settings: Settings) -> int:
    from pathlib import Path

    from app import ops

    try:
        if args.cmd == "backup":
            print(f"Backup written: {ops.backup(settings.database_url)}")
        elif args.cmd == "list-backups":
            backups = ops.list_backups()
            for b in backups:
                print(f"  {b.name}  ({b.stat().st_size // 1024} KiB)")
            if not backups:
                print("No backups yet. Run: python -m app.cli backup")
        elif args.cmd == "restore":
            path = Path(args.file)
            if not path.is_absolute() and not path.exists():
                path = ops.BACKUP_DIR / path
            rev = ops.validate_backup(path)
            if not args.yes:
                print(f"{path.name} is valid (schema {rev}). Stop the backend, then re-run "
                      "with --yes. Your current data will be backed up first.")
                return 2
            safety, rev = ops.restore(settings.database_url, path, alembic_config)
            print(f"Restored {path.name} (schema {rev}); previous data saved to {safety}")
        elif args.cmd == "reset":
            if not args.yes:
                print("This empties the database (a backup is taken first). Stop the backend, "
                      "then re-run with --yes.")
                return 2
            safety = ops.reset(settings.database_url, alembic_config)
            print(f"Database reset. Previous data saved to {safety}")
        elif args.cmd == "demo":
            from app.demo import build_demo

            summary = build_demo(cfg_factory=alembic_config)
            print("Offline demo database built (SYNTHETIC data, MOCK- markets):")
            for k, v in summary.items():
                print(f"  {k}: {v}")
            print("Start it with: .\\scripts\\start-demo.ps1  (your real data is untouched)")
    except ops.OpsError as e:
        print(f"Error: {e}")
        return 1
    return 0


def _paper_cmd(args: argparse.Namespace, settings: Settings) -> int:
    import uuid
    from decimal import Decimal, InvalidOperation

    from sqlalchemy import select

    from app.db.models import Market
    from app.paper.replay import replay
    from app.paper.service import OrderRequest, account_summary, positions, settle, submit_order
    from app.paper.simulator import SCENARIOS
    from app.signals.fees import load_schedules

    engine = make_engine(settings.database_url)
    clock = SystemClock()
    try:
        factory = make_session_factory(engine)
        with factory() as s:
            if args.cmd == "paper-order":
                m = s.scalar(select(Market).where(Market.external_ticker == args.ticker))
                if m is None:
                    print(f"Unknown market {args.ticker}")
                    return 1
                try:
                    limit = Decimal(args.limit_price)
                except InvalidOperation:
                    print("limit_price must be a decimal like 0.45")
                    return 2
                res = submit_order(s, settings, OrderRequest(
                    client_order_id=f"cli-{uuid.uuid4().hex[:16]}", market_id=m.id,
                    side=args.side, action=args.action, quantity=Decimal(args.quantity),
                    limit_price=limit, scenario=args.scenario or settings.paper_default_scenario,
                ), clock.now())
                s.commit()
                o = res.order
                print(f"{o.status}: {o.action} {o.filled_quantity}/{o.quantity} {o.side} "
                      f"{args.ticker} limit {o.limit_price} [{o.scenario}]"
                      + (f" reason={o.reject_reason}" if o.reject_reason else ""))
                if not o.fee_schedule_verified and o.status in ("FILLED", "PARTIAL"):
                    print("Note: fees from an UNVERIFIED schedule.")
                print("Simulated only: no exchange was contacted.")
                return 0
            if args.cmd == "paper-account":
                summ, rows = account_summary(s, clock.now())
                print(f"cash={summ.cash} open_value={summ.open_value} equity={summ.equity} "
                      f"realized={summ.realized:.4f} unrealized={summ.unrealized:.4f}")
                for p, mk, unr in rows:
                    t = s.get(Market, p.market_id).external_ticker
                    state = "SETTLED" if p.settled else ("HELD" if p.held else "open")
                    print(f"  {t} {p.side} open={p.open_qty} avg={p.avg_cost:.4f} "
                          f"realized={p.realized:.4f} unrealized={unr:.4f} [{state}]"
                          + (f" ({mk.note})" if mk.note else ""))
                for n in summ.notes:
                    print(f"Note: {n}")
                return 0
            if args.cmd == "paper-settle":
                held = sorted({s.get(Market, p.market_id).external_ticker
                               for p in positions(s).values() if p.open_qty > 0})
                live = [t for t in held if not t.startswith("MOCK-")]
                if live:
                    from app.adapters.kalshi_public import KalshiPublicMarketAdapter
                    from app.db.repositories import MarketRepository

                    adapter = KalshiPublicMarketAdapter.from_settings(settings, clock)
                    try:
                        res = adapter.refresh_tickers(live)
                    finally:
                        adapter.client.close()
                    repo = MarketRepository(s, clock)
                    for snap in res.snapshots:
                        repo.upsert_snapshot(snap, source=adapter.name)
                    for e in res.errors:
                        print(f"  refresh error {e.scope}: {e.code}")
                for st in settle(s, clock.now()):
                    t = s.get(Market, st.market_id).external_ticker
                    print(f"{st.status}: {t} exchange={st.exchange_result} "
                          f"evidence={st.evidence_check}")
                s.commit()
                print("Settlement only uses FINALIZED exchange results.")
                return 0
            if args.cmd == "paper-replay":
                sc = SCENARIOS[args.scenario or settings.paper_default_scenario]
                rep = replay(s, sc, clock.now(), load_schedules())
                print(f"Replay [{sc.name}]: signals={rep.n_signals} resolved={rep.n_resolved} "
                      f"cost={rep.total_cost} realized_pnl={rep.realized_pnl} "
                      f"brier={rep.resolved_brier}")
                for t in rep.trades:
                    print(f"  {t.status:9} {t.market_ticker} {t.side} {t.filled}/{t.requested} "
                          f"outcome={t.outcome}")
                print("Simulation of research signals; not evidence of real returns.")
                return 0
    finally:
        engine.dispose()
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
