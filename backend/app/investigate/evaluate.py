"""Offline evidence-quality evaluation for investigations (no network, no Brave credits).

Measures, over a set of results (stored investigations or test fixtures):
- contract mapping: side, market kind and line agree with the exact Kalshi contract;
- source time leakage: sources published after the game started, and stats updated after it;
- unsupported claims and citations: unverified findings, factual/statistical findings without
  a source;
- conflicts and duplication: reports that disagree (e.g. goalies), syndicated copies;
- added value: how often structured data contributes a finding with numbers no headline has;
- missingness by sport/league: which evidence was absent, from errors and gaps;
- calibration: only where a separately validated numeric model exists (none today, so it's
  reported as not applicable rather than computed on frequencies).

Errors are classed separately: permission (a source switched off, not permitted or blocked)
vs data/source (unavailable, HTTP, no rows) vs model (local model offline or rejected output).
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.investigate import schemas as S

PERMISSION = re.compile(r"switched off|not permitted|blocked|disabled|isn't set up", re.I)
MODEL = re.compile(r"local model|model's takeaway|ollama", re.I)
NUM = re.compile(r"\d+(?:\.\d+)?")
STRUCTURED_IDS = ("E1", "E2", "M1", "F1", "W1")


@dataclass
class MappingCase:
    """One expected mapping for a Kalshi contract (fixtures or hand-checked live tickers)."""

    ticker: str
    side: str
    kind: str
    threshold: float | None


@dataclass
class Report:
    results: int = 0
    mapping_checked: int = 0
    mapping_errors: list[str] = field(default_factory=list)
    leaked_sources: int = 0
    stats_after_start: int = 0
    findings: int = 0
    unverified: int = 0
    uncited_facts: int = 0
    news_sources: int = 0
    duplicates: int = 0
    conflicts: int = 0
    structured_adds: int = 0
    missing_by_league: dict[str, Counter[str]] = field(default_factory=lambda: defaultdict(Counter))
    errors_by_class: Counter[str] = field(default_factory=Counter)
    calibration: str = "not applicable: no separately validated numeric model"

    def rates(self) -> dict[str, Any]:
        def r(a: int, b: int) -> float | None:
            return None if b == 0 else round(a / b, 3)

        return {
            "results": self.results,
            "mapping_accuracy": r(
                self.mapping_checked - len(self.mapping_errors), self.mapping_checked
            ),
            "mapping_errors": self.mapping_errors,
            "leaked_sources": self.leaked_sources,
            "stats_updated_after_start": self.stats_after_start,
            "unsupported_claim_rate": r(self.unverified, self.findings),
            "uncited_fact_rate": r(self.uncited_facts, self.findings),
            "duplicate_rate": r(self.duplicates, self.news_sources),
            "conflicts": self.conflicts,
            "structured_adds_rate": r(self.structured_adds, self.results),
            "missing_by_league": {k: dict(v) for k, v in self.missing_by_league.items()},
            "errors_by_class": dict(self.errors_by_class),
            "calibration": self.calibration,
        }


def classify_error(msg: str) -> str:
    if PERMISSION.search(msg):
        return "permission"
    if MODEL.search(msg):
        return "model"
    return "data_or_source"


def check_mapping(r: S.Result, case: MappingCase) -> str | None:
    h = r.hypothesis
    if h.ticker != case.ticker:
        return None
    problems = []
    if h.side != case.side:
        problems.append(f"side {h.side} != {case.side}")
    if h.market_type != case.kind:
        problems.append(f"kind {h.market_type} != {case.kind}")
    if (h.threshold is None) != (case.threshold is None) or (
        h.threshold is not None
        and case.threshold is not None
        and abs(h.threshold - case.threshold) > 1e-9
    ):
        problems.append(f"line {h.threshold} != {case.threshold}")
    if (h.side == "no") != h.statement.startswith("NOT:"):
        problems.append("statement doesn't say which side")
    return f"{case.ticker}:{case.side}: " + "; ".join(problems) if problems else None


def _dt(x: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(x) if x else None
    except ValueError:
        return None


def evaluate(
    results: list[S.Result],
    cases: list[MappingCase] | None = None,
    starts: dict[str, datetime] | None = None,
) -> Report:
    """`starts`: event ticker -> game start, for leakage checks (from the catalog)."""
    rep = Report()
    by_key = {(c.ticker, c.side): c for c in cases or []}
    for r in results:
        rep.results += 1
        h = r.hypothesis
        case = by_key.get((h.ticker, h.side))
        if case is not None:
            rep.mapping_checked += 1
            bad = check_mapping(r, case)
            if bad:
                rep.mapping_errors.append(bad)
        start = (starts or {}).get(h.event_ticker)
        news = [s for s in r.sources if s.access != "internal"]
        rep.news_sources += len(news)
        rep.duplicates += sum(1 for s in news if s.duplicate_of)
        if start is not None:
            for s in r.sources:
                pub = _dt(s.published_at)
                if pub is None or pub <= start:
                    continue
                if s.access == "internal":
                    rep.stats_after_start += 1
                else:
                    rep.leaked_sources += 1
        every = r.summary.findings + [
            f for f in r.details.supports + r.details.against if f not in r.summary.findings
        ]
        rep.findings += len(every)
        rep.unverified += sum(1 for f in every if not f.verified)
        rep.uncited_facts += sum(
            1 for f in every if f.kind in ("factual", "statistical") and not f.source_ids
        )
        if any(
            "conflict" in f.text.lower()
            or "disagree" in f.text.lower()
            or "name different starters" in f.text
            for f in every
        ):
            rep.conflicts += 1
        headline_nums = {n for s in news for n in NUM.findall(s.title)}
        if any(
            any(i in STRUCTURED_IDS for i in f.source_ids)
            and (set(NUM.findall(f.text)) - headline_nums)
            for f in every
        ):
            rep.structured_adds += 1
        league = h.league or "unknown"
        for e in r.processing.errors:
            rep.errors_by_class[classify_error(e)] += 1
            rep.missing_by_league[league][classify_error(e)] += 1
        for g in r.summary.gaps:
            low = g.lower()
            tag = (
                "goalie"
                if "goal" in low and "start" in low
                else "lineup"
                if "playing" in low or "injur" in low
                else "news"
                if "news" in low or "article" in low
                else "price"
                if "price" in low
                else "other"
            )
            rep.missing_by_league[league][f"gap:{tag}"] += 1
        if (
            r.price_assessment.model_p is not None
            and r.price_assessment.model_name
            and (
                "calibrated" in r.price_assessment.model_name.lower()
                and "not calibrated" not in r.price_assessment.model_name.lower()
            )
        ):
            rep.calibration = "a calibrated model exists: evaluate it against settled outcomes"
    return rep
