"""Kalshi combos (multivariate markets): which events can be combined, and how settled
combos actually paid off versus the price they traded at.

Facts from the public API (checked 2026-11-18):
- Combos live in a few "collections" (e.g. KXMVECROSSCATEGORY-R) that each list the events
  whose markets may be legs (thousands of sports/other events), 2+ legs, no fixed max.
- Combo markets are created on request and priced privately by market makers (RFQ): almost
  none have a public two-sided quote, so there is no combo orderbook to scan.
- Settled combo markets do expose their last trade price and result. That is what the
  study below measures: across many settled combos, did YES (the combo buyer) hit as often
  as the price implied?

Caveat, stated in the UI: the LAST trade price is not exactly what every buyer paid, and
late trades (after some legs finished) pull prices toward the outcome, which would make
combos look BETTER than they were, not worse.
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.base import AdapterError
from app.adapters.kalshi_public import KalshiPublicClient
from app.catalog.store import _upsert
from app.db.models import AuditEvent, CatalogComboEvent

STUDY_ACTION = "COMBO_STUDY"


def refresh_combo_eligibility(factory: sessionmaker[Session], client: KalshiPublicClient,
                              now: datetime) -> int:
    body = client.get("/multivariate_event_collections", {"status": "open", "limit": 200})
    cols = body.get("multivariate_contracts")
    if not isinstance(cols, list):
        raise AdapterError("Missing 'multivariate_contracts'")
    by_event: dict[str, set[str]] = defaultdict(set)
    for c in cols:
        if not isinstance(c, dict) or not c.get("collection_ticker"):
            continue
        for ev in c.get("associated_event_tickers") or []:
            if isinstance(ev, str) and ev:
                by_event[ev].add(str(c["collection_ticker"]))
    rows = [{"event_ticker": e, "collections": ",".join(sorted(cs)), "refreshed_at": now}
            for e, cs in by_event.items()]
    with factory() as s:
        _upsert(s, CatalogComboEvent.__table__, rows, "event_ticker")
        s.execute(delete(CatalogComboEvent).where(CatalogComboEvent.refreshed_at < now))
        s.commit()
    return len(rows)


def combo_collections(s: Session, event_tickers: list[str]) -> dict[str, list[str]]:
    rows = s.execute(select(CatalogComboEvent.event_ticker, CatalogComboEvent.collections)
                     .where(CatalogComboEvent.event_ticker.in_(event_tickers))).all()
    return {e: c.split(",") for e, c in rows}


def _bucket_legs(n: int) -> str:
    return "2 legs" if n == 2 else "3 legs" if n == 3 else "4-5 legs" if n <= 5 else "6+ legs"


def _bucket_price(p: float) -> str:
    return "under 5¢" if p < .05 else "5–15¢" if p < .15 else "15–35¢" if p < .35 else "35¢+"


def summarize(rows: list[tuple[float, bool]]) -> dict[str, Any] | None:
    """rows: (last trade price, YES hit). 'return_per_dollar' = what one contract of each
    would have paid back per $1 spent (before fees)."""
    if not rows:
        return None
    n = len(rows)
    paid = sum(p for p, _ in rows)
    won = sum(1 for _, w in rows if w)
    avg = paid / n
    return {"n": n, "avg_price": round(avg, 4), "hit_rate": round(won / n, 4),
            "edge": round(won / n - avg, 4),
            "se": round(math.sqrt(max(avg * (1 - avg), 1e-9) / n), 4),
            "return_per_dollar": round(won / paid, 4) if paid else None}


def study(markets: list[dict[str, Any]]) -> dict[str, Any]:
    rows: list[tuple[float, bool, int]] = []
    for m in markets:
        try:
            lp = float(m.get("last_price_dollars") or 0)
            vol = float(m.get("volume_fp") or 0)
        except (TypeError, ValueError):
            continue
        if vol <= 0 or not 0 < lp < 1 or m.get("result") not in ("yes", "no"):
            continue
        rows.append((lp, m["result"] == "yes", len(m.get("mve_selected_legs") or [])))
    by_legs: dict[str, list[tuple[float, bool]]] = defaultdict(list)
    by_price: dict[str, list[tuple[float, bool]]] = defaultdict(list)
    for p, w, legs in rows:
        by_legs[_bucket_legs(max(legs, 2))].append((p, w))
        by_price[_bucket_price(p)].append((p, w))
    order_l = ["2 legs", "3 legs", "4-5 legs", "6+ legs"]
    order_p = ["under 5¢", "5–15¢", "15–35¢", "35¢+"]
    return {
        "overall": summarize([(p, w) for p, w, _ in rows]),
        "by_legs": [{"bucket": k, **s} for k in order_l if (s := summarize(by_legs[k]))],
        "by_price": [{"bucket": k, **s} for k in order_p if (s := summarize(by_price[k]))],
        "markets_scanned": len(markets),
    }


def run_combo_study(factory: sessionmaker[Session], client: KalshiPublicClient,
                    now: datetime, max_pages: int = 40) -> dict[str, Any]:
    markets: list[dict[str, Any]] = []
    cursor = None
    for _ in range(max_pages):
        params: dict[str, Any] = {"mve_filter": "only", "status": "settled", "limit": 1000}
        if cursor:
            params["cursor"] = cursor
        body = client.get("/markets", params)
        page = body.get("markets")
        if not isinstance(page, list):
            raise AdapterError("Missing 'markets' array")
        markets.extend(m for m in page if isinstance(m, dict))
        cursor = body.get("cursor") or None
        if not cursor:
            break
    out = study(markets)
    out["generated_at"] = now.isoformat()
    with factory() as s:
        s.add(AuditEvent(at=now, actor="combos", action=STUDY_ACTION, object_type="study",
                         object_id=None, metadata_json=json.dumps(out)))
        s.commit()
    return out


def latest_study(s: Session) -> dict[str, Any] | None:
    row = s.scalars(select(AuditEvent).where(AuditEvent.action == STUDY_ACTION)
                    .order_by(AuditEvent.at.desc()).limit(1)).first()
    return json.loads(row.metadata_json) if row else None


def history_for(study_: dict[str, Any] | None, legs: int) -> dict[str, Any] | None:
    if not study_ or legs < 2:
        return None
    key = _bucket_legs(legs)
    return next((b for b in study_.get("by_legs", []) if b["bucket"] == key), None)
