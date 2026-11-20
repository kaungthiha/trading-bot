"""Typed contract for one investigation. Mirrors frontend/src/api/types.ts (InvestigationResult).
The summary and the full view are both read from this one object."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Side = Literal["yes", "no"]
MarketKind = Literal["moneyline", "spread", "total", "team_total", "player_prop", "other"]
ClaimKind = Literal["factual", "statistical", "analyst_opinion", "prediction", "interpretation"]
Stance = Literal["supports", "opposes", "neutral"]


class Hypothesis(BaseModel):
    ticker: str
    event_ticker: str
    side: Side
    sport: str
    league: str
    market_type: MarketKind
    threshold: float | None
    subject: str | None
    label: str
    statement: str
    snapshot_at: str | None
    rules_url: str | None


class Quote(BaseModel):
    ask: float | None
    side: Side
    observed_at: str | None
    fresh: bool
    snapshot_ref: str | None


class Finding(BaseModel):
    text: str = Field(max_length=400)
    kind: ClaimKind
    stance: Stance
    source_ids: list[str] = Field(default_factory=list, max_length=6)
    verified: bool


class Source(BaseModel):
    id: str
    url: str
    title: str
    publisher: str
    author: str | None = None
    published_at: str | None = None
    retrieved_at: str
    access: Literal["headline", "snippet", "full_text", "internal"]
    duplicate_of: str | None = None
    line_match: Literal["exact", "different_line", "past_matchup", "unknown"] = "unknown"


class Price(BaseModel):
    ask: float | None
    model_p: float | None
    model_band: tuple[float, float] | None
    model_name: str | None
    raw_diff: float | None
    conservative_edge: float | None
    break_even: float | None
    walk_away: float | None
    fee_per_contract: float | None
    slippage_per_contract: float | None
    assumptions: list[str]
    abstain_reasons: list[str]


class Summary(BaseModel):
    takeaway: str = Field(max_length=600)
    findings: list[Finding] = Field(max_length=3)
    gaps: list[str]
    stance: Literal["supports", "challenges", "insufficient"]
    uncertainty: str


class Details(BaseModel):
    supports: list[Finding]
    against: list[Finding]
    methodology: list[str]
    data_gaps: list[str]
    rules_excerpt: str | None = None


class Processing(BaseModel):
    model: str | None
    searches: int
    cache: Literal["hit", "miss", "none"]
    errors: list[str]
    partial_reasons: list[str]


class Result(BaseModel):
    investigation_id: str
    status: Literal["running", "done", "partial", "failed"]
    created_at: str
    completed_at: str | None
    stale_at: str | None
    hypothesis: Hypothesis
    quote: Quote
    summary: Summary
    price_assessment: Price
    details: Details
    sources: list[Source]
    processing: Processing
