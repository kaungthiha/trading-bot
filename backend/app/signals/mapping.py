"""Propose links between exchange markets and model contract definitions.

The parser only PROPOSES. A human must confirm (CLI) after reading the official rules.
Each mapping is pinned to the rules-text hash it was checked against: a rules change
means the mapping no longer applies until re-proposed and re-confirmed.

KXCPI (checked against live rules 2026-11-18):
  ticker  KXCPI-26DEC-T0.3
  rules   "If the Consumer Price Index (CPI) increases by more than 0.3% in December 2026,
           as reported to one decimal place, then the market resolves to Yes."
  + "the Expiration Value is the single-decimal value published at the Source Agency"
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Market, MarketMapping, MarketRuleVersion

CONTRACT_CPI_MOM = "CPI_MOM_SA_FIRST"
_MONTHS = {m: i for i, m in enumerate(
    ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], 1)}
_MONTH_NAMES = {m: i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July", "August", "September",
     "October", "November", "December"], 1)}
_KXCPI_TICKER = re.compile(r"^KXCPI-(\d{2})([A-Z]{3})-T(-?\d+(?:\.\d+)?)$")
# Two rule templates observed live on 2026-11-18 (both state single-decimal resolution):
#   26DEC: "...increases by more than 0.3% in December 2026, as reported to one decimal place"
#   26NOV: "...increases by more than 0.3% (single-decimal) in November 2026"
# Anything else is rejected rather than guessed.
_KXCPI_RULES = (
    re.compile(r"increases by more than (-?\d+(?:\.\d+)?)% in ([A-Z][a-z]+) (\d{4}), "
               r"as reported to one decimal place"),
    re.compile(r"increases by more than (-?\d+(?:\.\d+)?)% \(single-decimal\) in "
               r"([A-Z][a-z]+) (\d{4})"),
)
_FIRST_PRINT_RULE = "single-decimal value published at the Source Agency"


@dataclass(frozen=True)
class Proposal:
    status: str  # proposed | rejected
    contract_type: str
    reference_month: date | None
    threshold: Decimal | None
    notes: list[str] = field(default_factory=list)


def propose_cpi_mom(market: Market, rules_text: str, contract_terms_url: str | None) -> Proposal:
    def reject(why: str) -> Proposal:
        return Proposal("rejected", CONTRACT_CPI_MOM, None, None, [why])

    if market.series_ticker != "KXCPI":
        return reject("Not a KXCPI market")
    if market.market_type != "binary":
        return reject(f"Market type {market.market_type!r} is not binary")
    t = _KXCPI_TICKER.match(market.external_ticker)
    if not t:
        return reject("Ticker does not match KXCPI-YYMON-T<threshold>")
    yy, mon, thr = t.groups()
    if mon not in _MONTHS:
        return reject(f"Unknown month code {mon}")
    ticker_month = date(2000 + int(yy), _MONTHS[mon], 1)
    ticker_thr = Decimal(thr)

    r = next((m for pat in _KXCPI_RULES if (m := pat.search(rules_text))), None)
    if not r:
        return reject("Rules text matches no recognised KXCPI template (must state 'more than "
                      "X%' for a named month with single-decimal resolution)")
    rule_thr, rule_mon, rule_year = Decimal(r.group(1)), r.group(2), int(r.group(3))
    if rule_mon not in _MONTH_NAMES:
        return reject(f"Unknown month name {rule_mon!r} in rules")
    rule_month = date(rule_year, _MONTH_NAMES[rule_mon], 1)
    if rule_thr != ticker_thr or rule_month != ticker_month:
        return reject(f"Ticker ({ticker_month:%Y-%m}, {ticker_thr}) disagrees with rules "
                      f"({rule_month:%Y-%m}, {rule_thr})")
    if ticker_thr != ticker_thr.quantize(Decimal("0.1")):
        return reject("Threshold is not on the 0.1 grid")

    notes = [
        "Rules: strictly 'more than' the threshold on the single-decimal value "
        "-> matches the model's strict > on the rounded value.",
    ]
    if _FIRST_PRINT_RULE in rules_text:
        notes.append("Rules: settles on the value published at the source agency at "
                     "expiration -> first print.")
    else:
        notes.append("CHECK: rules do not state that the first published value is used.")
    if "seasonally adjusted" not in rules_text.lower():
        notes.append(
            "CHECK: rules text does not say seasonally adjusted (SA). The model forecasts the "
            "SA headline CPI-U change (what BLS headlines monthly). Verify in the contract "
            f"terms before confirming: {contract_terms_url or 'contract terms PDF'}"
        )
    notes.append("CHECK: rules mention government-shutdown delays extending expiration; the "
                 "model assumes a normal release.")
    return Proposal("proposed", CONTRACT_CPI_MOM, rule_month, rule_thr, notes)


def current_rules(session: Session, market_id: str) -> MarketRuleVersion | None:
    return session.scalar(select(MarketRuleVersion).where(
        MarketRuleVersion.market_id == market_id, MarketRuleVersion.is_current.is_(True)))


def latest_mapping(session: Session, market_id: str) -> MarketMapping | None:
    return session.scalar(
        select(MarketMapping).where(MarketMapping.market_id == market_id)
        .order_by(MarketMapping.created_at.desc()).limit(1)
    )


def _strictly_after(latest: MarketMapping | None, now: datetime) -> datetime:
    """Mapping order is by created_at; guarantee a new row sorts after the previous one."""
    if latest is not None and now <= latest.created_at:
        return latest.created_at + timedelta(microseconds=1)
    return now


def propose_all(session: Session, now: datetime) -> list[tuple[Market, MarketMapping]]:
    """Create proposals for KXCPI markets that have no mapping for their CURRENT rules."""
    created = []
    for m in session.scalars(select(Market).where(Market.series_ticker == "KXCPI")).all():
        rules = current_rules(session, m.id)
        if rules is None:
            continue
        latest = latest_mapping(session, m.id)
        p = propose_cpi_mom(m, rules.rules_text, rules.official_source_url)
        if latest is not None and latest.rules_hash == rules.hash:
            # Human decisions always stand. A previous *parser* rejection may be revisited
            # (e.g. after a new rule template is recognised) if the outcome now differs.
            if latest.actor != "parser" or latest.status == p.status:
                continue
        row = MarketMapping(
            created_at=_strictly_after(latest, now), market_id=m.id, contract_type=p.contract_type,
            reference_month=p.reference_month.isoformat() if p.reference_month else None,
            threshold=p.threshold, rules_hash=rules.hash, status=p.status, actor="parser",
            notes_json=json.dumps(p.notes),
        )
        session.add(row)
        created.append((m, row))
    session.flush()
    return created


class MappingError(ValueError):
    pass


def decide(session: Session, market: Market, now: datetime, *, confirm: bool,
           note: str | None = None) -> MarketMapping:
    """Human decision. Confirm only a PROPOSED mapping whose rules are still current."""
    latest = latest_mapping(session, market.id)
    rules = current_rules(session, market.id)
    if latest is None or rules is None:
        raise MappingError("No proposal exists for this market; run propose-mappings first")
    if latest.rules_hash != rules.hash:
        raise MappingError("Rules changed since the proposal; run propose-mappings again")
    if confirm and latest.status != "proposed":
        raise MappingError(f"Latest mapping is {latest.status!r}; only proposals can be confirmed")
    notes = json.loads(latest.notes_json) + ([f"User note: {note}"] if note else [])
    row = MarketMapping(
        created_at=_strictly_after(latest, now), market_id=market.id,
        contract_type=latest.contract_type,
        reference_month=latest.reference_month, threshold=latest.threshold,
        rules_hash=rules.hash, status="confirmed" if confirm else "rejected", actor="user",
        notes_json=json.dumps(notes),
    )
    session.add(row)
    session.flush()
    return row
