"""Persistence for market snapshots. Snapshot rows are inserted, never updated."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import Clock
from app.db.models import AuditEvent, Market, MarketRuleVersion, QuoteSnapshot
from app.domain.models import MarketSnapshot
from app.domain.pricing import derive_quote


def rules_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class MarketRepository:
    def __init__(self, session: Session, clock: Clock) -> None:
        self.s = session
        self.clock = clock

    def upsert_snapshot(self, snap: MarketSnapshot, source: str) -> Market:
        """Idempotently record a market snapshot: update mutable market metadata,
        append a new rule version only if the rule text changed, and append a quote
        only if this observation time has not been stored before."""
        now = self.clock.now()
        market = self.s.scalar(select(Market).where(Market.external_ticker == snap.external_ticker))
        if market is None:
            market = Market(external_ticker=snap.external_ticker)
            self.s.add(market)
        market.exchange = snap.exchange
        market.event_ticker = snap.event_ticker
        market.title = snap.title
        market.category = snap.category
        market.status = snap.status.value
        market.close_at = snap.close_at
        market.notional_value = snap.notional_value
        market.price_ranges_json = json.dumps(
            [r.model_dump(mode="json") for r in snap.price_ranges]
        )
        market.is_mock = snap.is_mock
        market.updated_at = now
        self.s.flush()

        h = rules_hash(snap.rules_text)
        current = self.current_rules(market.id)
        if current is None or current.hash != h:
            if current is not None:
                current.is_current = False
            self.s.add(
                MarketRuleVersion(
                    market_id=market.id,
                    rules_text=snap.rules_text,
                    official_source_url=snap.official_source_url,
                    hash=h,
                    observed_at=now,
                    is_current=True,
                )
            )
            self._audit("rules_version_recorded", "market", market.id, {"hash": h})

        observed = snap.orderbook.observed_at
        exists = self.s.scalar(
            select(QuoteSnapshot.id).where(
                QuoteSnapshot.market_id == market.id, QuoteSnapshot.observed_at == observed
            )
        )
        if exists is None:
            q = derive_quote(snap.orderbook, snap.notional_value)
            self.s.add(
                QuoteSnapshot(
                    market_id=market.id,
                    observed_at=observed,
                    received_at=now,
                    yes_bid=q.yes_bid,
                    no_bid=q.no_bid,
                    yes_ask_derived=q.yes_ask,
                    no_ask_derived=q.no_ask,
                    depth_json=snap.orderbook.model_dump_json(include={"yes_bids", "no_bids"}),
                    raw_ref=f"{source}:{snap.external_ticker}",
                )
            )
        self.s.flush()
        return market

    def list_markets(self, category: str | None, limit: int, offset: int) -> Sequence[Market]:
        stmt = select(Market).order_by(Market.close_at, Market.external_ticker)
        if category:
            stmt = stmt.where(Market.category == category)
        return self.s.scalars(stmt.limit(limit).offset(offset)).all()

    def get(self, market_id: str) -> Market | None:
        return self.s.get(Market, market_id)

    def current_rules(self, market_id: str) -> MarketRuleVersion | None:
        return self.s.scalar(
            select(MarketRuleVersion).where(
                MarketRuleVersion.market_id == market_id, MarketRuleVersion.is_current.is_(True)
            )
        )

    def latest_quote(self, market_id: str) -> QuoteSnapshot | None:
        return self.s.scalar(
            select(QuoteSnapshot)
            .where(QuoteSnapshot.market_id == market_id)
            .order_by(QuoteSnapshot.observed_at.desc())
            .limit(1)
        )

    def _audit(self, action: str, obj_type: str, obj_id: str | None, meta: dict) -> None:
        self.s.add(
            AuditEvent(
                at=self.clock.now(),
                actor="system",
                action=action,
                object_type=obj_type,
                object_id=obj_id,
                metadata_json=json.dumps(meta),
            )
        )
