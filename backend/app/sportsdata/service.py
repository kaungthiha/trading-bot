"""Evidence for a set of legs, shared by the Games slip and the My trades open positions."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.catalog import games
from app.sportsdata.espn import LEAGUES, EspnSource
from app.sportsdata.evidence import EvidenceService, adjusted_probability


def evidence_for(session: Session, src: EspnSource, parsed: list[tuple[str, str]],
                 briefs: bool = False
                 ) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    """(evidence, leg rows, tickers missing from the catalog). Missing legs are skipped.
    briefs=True adds the qualitative case for and against each leg (app.sportsdata.briefs)."""
    specs = games.market_specs(session, [t for t, _ in parsed])
    missing = [t for t, _ in parsed if t not in specs]
    team_names: dict[str, dict[str, str]] = {}
    for info in specs.values():
        gk, pre = info["game_key"], info["prefix"]
        if pre and gk not in team_names:
            team_names[gk] = games.list_games_teams(session, pre, gk)
    rows = [{"ticker": t, "side": side, **specs[t]} for t, side in parsed if t in specs]
    out = EvidenceService(src, briefs).legs(rows, team_names) if rows else {"legs": [],
                                                                     "correlation": []}
    probs: dict[str, float] = {}
    independent: float | None = 1.0 if rows else None
    for r in rows:
        p = r["implied"]
        p = None if p is None else (p if r["side"] == "yes" else 1 - p)
        if p is None:
            independent = None
        else:
            probs[r["ticker"]] = p
            independent = None if independent is None else independent * p
    out["independent_probability"] = None if independent is None else round(independent, 4)
    out["adjusted_probability"] = adjusted_probability(independent, out["correlation"], probs)
    out["leagues"] = sorted(LEAGUES)
    return out, rows, missing
