"""Pull your full history (live + archived) and upsert it by Kalshi's ids. Small accounts
fit in a few requests, so every sync is a full sync: nothing depends on timestamp units."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from app.catalog.store import _dec, _dt, _upsert
from app.db.models import AccountFill, AccountPosition, AccountSettlement, AccountSync
from app.history.client import AccountError, AccountReader

ZERO = Decimal(0)


def side_and_action(f: dict[str, Any]) -> tuple[str, str] | None:
    """Which contract (yes/no) and whether you bought or sold it.

    Prefer the explicit `side`/`action` fields. Otherwise infer from `outcome_side` and
    `book_side` (bid = the YES-book bid side): yes+bid = buy YES, no+ask = buy NO,
    yes+ask = sell YES, no+bid = sell NO. This inference is checked against Kalshi's own
    realized P&L in the report ("reconciliation")."""
    side, action = f.get("side"), f.get("action")
    if side in ("yes", "no") and action in ("buy", "sell"):
        return side, action
    o, b = f.get("outcome_side"), f.get("book_side")
    if o not in ("yes", "no") or b not in ("bid", "ask"):
        return None
    buy = (o == "yes" and b == "bid") or (o == "no" and b == "ask")
    return o, "buy" if buy else "sell"


def fill_row(f: dict[str, Any], source: str) -> dict[str, Any] | None:
    sa = side_and_action(f)
    fid = f.get("fill_id") or f.get("trade_id")
    ticker = f.get("ticker") or f.get("market_ticker")
    yes = _dec(f.get("yes_price_dollars"))
    no = _dec(f.get("no_price_dollars"))
    count = _dec(f.get("count_fp"))
    at = _dt(f.get("created_time"))
    if not (sa and fid and ticker and yes is not None and count and at):
        return None
    side, action = sa
    return {"fill_id": str(fid), "ticker": str(ticker), "order_id": str(f.get("order_id") or ""),
            "side": side, "action": action, "is_taker": bool(f.get("is_taker")),
            "count": count, "price": yes if side == "yes" else (no if no is not None else 1 - yes),
            "yes_price": yes, "fee": _dec(f.get("fee_cost")) or ZERO, "created_at": at,
            "source": source}


def settlement_row(x: dict[str, Any]) -> dict[str, Any] | None:
    at = _dt(x.get("settled_time"))
    if not x.get("ticker") or at is None:
        return None
    rev = _dec(x.get("revenue")) or ZERO
    return {"ticker": str(x["ticker"]), "event_ticker": str(x.get("event_ticker") or ""),
            "market_result": str(x.get("market_result") or "")[:8],
            "yes_count": _dec(x.get("yes_count_fp")) or ZERO,
            "yes_cost": _dec(x.get("yes_total_cost_dollars")) or ZERO,
            "no_count": _dec(x.get("no_count_fp")) or ZERO,
            "no_cost": _dec(x.get("no_total_cost_dollars")) or ZERO,
            "revenue": rev / 100,  # API sends integer cents
            "fee": _dec(x.get("fee_cost")) or ZERO, "settled_at": at}


def position_row(p: dict[str, Any], source: str) -> dict[str, Any] | None:
    if not p.get("ticker"):
        return None
    return {"ticker": str(p["ticker"]), "position": _dec(p.get("position_fp")) or ZERO,
            "exposure": _dec(p.get("market_exposure_dollars")) or ZERO,
            "realized_pnl": _dec(p.get("realized_pnl_dollars")) or ZERO,
            "fees_paid": _dec(p.get("fees_paid_dollars")) or ZERO,
            "total_traded": _dec(p.get("total_traded_dollars")) or ZERO,
            "last_updated": _dt(p.get("last_updated_ts")), "source": source}


@dataclass
class SyncResult:
    status: str
    message: str


def sync_account(factory: sessionmaker[Session], reader: AccountReader,
                 now: datetime) -> SyncResult:
    counts = {"fills": 0, "settlements": 0, "positions": 0}
    balance = value = None
    try:
        fills: dict[str, dict] = {}
        # Archived (older) first, then live, so live rows win on any overlap.
        for path, src in (("/historical/fills", "historical"), ("/portfolio/fills", "live")):
            for f in reader.paginate(path, "fills"):
                row = fill_row(f, src)
                if row:
                    fills[row["fill_id"]] = row
        settlements = {r["ticker"]: r for r in (settlement_row(x) for x in
                       reader.paginate("/portfolio/settlements", "settlements")) if r}
        positions: dict[str, dict] = {}
        for path, params, src in (("/historical/positions", {}, "historical"),
                                  ("/portfolio/positions", {"settlement_status": "all"}, "live")):
            for p in reader.paginate(path, "market_positions", params):
                row = position_row(p, src)
                if row:
                    positions[row["ticker"]] = row
        bal = reader.get("/portfolio/balance")
        balance = _dec(bal.get("balance_dollars")) or ((_dec(bal.get("balance")) or ZERO) / 100)
        value = (_dec(bal.get("portfolio_value")) or ZERO) / 100
        with factory() as s:
            _upsert(s, AccountFill.__table__, list(fills.values()), "fill_id")
            _upsert(s, AccountSettlement.__table__, list(settlements.values()), "ticker")
            _upsert(s, AccountPosition.__table__, list(positions.values()), "ticker")
            s.commit()
        counts = {"fills": len(fills), "settlements": len(settlements),
                  "positions": len(positions)}
        status, msg = "success", (f"{counts['fills']} fills, {counts['settlements']} "
                                  f"settlements, {counts['positions']} positions; balance "
                                  f"${balance:.2f}")
    except AccountError as e:
        status, msg = "failed", str(e)
    with factory() as s:
        s.add(AccountSync(at=now, status=status, balance=balance, portfolio_value=value,
                          message=msg, **counts))
        s.commit()
    if status == "success":
        from app.history.positions import safe_record_marks

        safe_record_marks(factory, now, "sync")
    return SyncResult(status, msg)
