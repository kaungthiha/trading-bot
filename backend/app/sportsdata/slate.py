"""Tonight's slate: 3-4 leg combo suggestions built from qualitative leg briefs.

How a suggestion is made (deterministic, no AI, nothing traded):
1. Every game of the league starting in the next 30 hours; per game the most-traded liquid
   full-game legs (both sides) get a brief (app.sportsdata.briefs).
2. A leg can join a combo only if its case is clear: at least two more points for than
   against, at most one against, priced 40-80% for the side, combinable on Kalshi, and no
   injury flag. One rung per player per stat; one leg per player.
3. Combos of 3 and 4 legs: at most two legs from one game, never winner + spread of one game
   (the second mostly repeats the first). Ranked by how clear the legs' cases are, then by
   price (fewer long shots).
4. Each combo is priced from the market legs, adjusted where same-game legs historically
   landed together, and shown with every leg's case and everything against it.

Kalshi's settled combos returned about $0.82-0.85 per $1 for 3-5 legs (before fees), so the
bar is high. These are leads to research, never instructions.
"""

from __future__ import annotations

import itertools
import logging
import math
import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from app.catalog import games
from app.catalog.combos import history_for, latest_study
from app.sportsdata.espn import EspnSource
from app.sportsdata.evidence import adjusted_probability
from app.sportsdata.ideas import _family, candidates
from app.sportsdata.service import evidence_for

log = logging.getLogger(__name__)

LEAGUES = ("KXNBA", "KXWNBA")   # leagues with an injury report and a team table
WINDOW = timedelta(hours=30)
MAX_GAMES = 15
PER_GAME = 30                   # most-traded liquid legs per game get a brief
LEG_MIN, LEG_MAX = 0.40, 0.80
MIN_SCORE = 2
POOL = 12
MAX_PER_GAME = 2
MAX_COMBOS = 3
FRESH = timedelta(minutes=15)


def _aware(d: Any) -> datetime | None:
    if not isinstance(d, datetime):
        return None
    return d if d.tzinfo else d.replace(tzinfo=UTC)


def tonight(s: Session, prefix: str, now: datetime) -> list[dict[str, Any]]:
    items = games.list_games(s, prefix[2:])["items"]
    out = [g for g in items if g["prefix"] == prefix and (t := _aware(g["occurs_at"]))
           and now < t < now + WINDOW]
    return out[:MAX_GAMES]


def _leg(lg: dict[str, Any], c: dict[str, Any], g: dict[str, Any], prefix: str
         ) -> dict[str, Any]:
    side = lg["side"]
    label = f"{c['group']} {c['label']}".strip()
    return {"ticker": lg["ticker"], "side": side, "label": label,
            "bet": f"{side.upper()} · {label}", "event_ticker": c["event_ticker"],
            "game_key": g["game_key"], "game": g["title"],
            "subject": (lg.get("subject") or {}).get("name"), "kind": lg.get("kind"),
            "price": lg.get("market"), "eligible": bool(c.get("eligible")),
            "family": _family(prefix, c["event_ticker"]), "brief": lg["brief"],
            "windows": lg.get("windows"), "line": lg.get("line")}


def clear_case(x: dict[str, Any]) -> bool:
    b, p = x["brief"], x["price"]
    return (x["eligible"] and p is not None and LEG_MIN <= p <= LEG_MAX
            and b["lean"] in ("strong", "mixed") and b["score"] >= MIN_SCORE
            and len(b["against"]) <= 1)


def pick_pool(legs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Clear-case legs, best rung per player/team per stat, one leg per player."""
    best: dict[tuple[str, str | None], dict[str, Any]] = {}
    for x in filter(clear_case, legs):
        k = (x["event_ticker"], x["subject"])
        cur = best.get(k)
        if cur is None or (x["brief"]["score"], x["price"]) > (cur["brief"]["score"],
                                                               cur["price"]):
            best[k] = x
    ranked = sorted(best.values(), key=lambda x: (-x["brief"]["score"], -x["price"]))
    pool: list[dict[str, Any]] = []
    players: set[str] = set()
    for x in ranked:
        if x["kind"] == "player_stat" and x["subject"] in players:
            continue
        if x["kind"] == "player_stat":
            players.add(x["subject"])
        pool.append(x)
    return pool[:POOL]


def combos_from(pool: list[dict[str, Any]]) -> list[tuple[dict[str, Any], ...]]:
    ranked = []
    for n in (3, 4):
        for legs in itertools.combinations(pool, n):
            if len({x["family"] for x in legs}) < n:
                continue
            per_game: dict[str, int] = {}
            for x in legs:
                per_game[x["game_key"]] = per_game.get(x["game_key"], 0) + 1
            if max(per_game.values()) > MAX_PER_GAME:
                continue
            clarity = sum(x["brief"]["score"] for x in legs) / n
            price = math.prod(x["price"] for x in legs)
            ranked.append((clarity, price, legs))
    ranked.sort(key=lambda t: (-t[0], -t[1]))
    chosen: list[tuple[dict[str, Any], ...]] = []
    for _, _, legs in ranked:
        ids = {x["ticker"] for x in legs}
        # Different suggestions, not one combo with a leg swapped.
        if all(len(ids & {x["ticker"] for x in c}) < min(len(c), len(legs)) - 1
               for c in chosen):
            chosen.append(legs)
        if len(chosen) >= MAX_COMBOS:
            break
    return chosen


def _combo(s: Session, src: EspnSource, legs: tuple[dict[str, Any], ...],
           study: dict[str, Any] | None) -> dict[str, Any]:
    prices = {x["ticker"]: float(x["price"]) for x in legs}
    market = math.prod(prices.values())
    together: list[dict[str, Any]] = []
    try:
        ev, _, _ = evidence_for(s, src, [(x["ticker"], x["side"]) for x in legs])
        together = [c for c in ev["correlation"] if c.get("lift")]
    except Exception:  # noqa: BLE001 - the market price alone still stands
        together = []
    adj = adjusted_probability(market, together, prices) or market
    risks = [{"leg": x["label"], "text": p["text"]} for x in legs for p in x["brief"]["against"]]
    risks += [{"leg": x["label"], "text": p["text"]} for x in legs
              for p in x["brief"]["context"] if p["kind"] in ("injury", "teammates")]
    return {
        "legs": [{k: x[k] for k in ("ticker", "side", "label", "bet", "event_ticker", "game",
                                    "price")} | {"headline": x["brief"]["headline"],
                                                 "why": x["brief"]["for"][:3]}
                 for x in legs],
        "games": len({x["game_key"] for x in legs}),
        "market": round(market, 4), "adjusted": round(adj, 4),
        "together": [{"team": c["team"], "lift": c["lift"], "games": c["games"]}
                     for c in together],
        "pays": round(1 / adj, 1) if adj > 0 else None,
        "risks": risks,
        "past": history_for(study, len(legs)),
    }


def build_slate(s: Session, src: EspnSource, prefix: str, now: datetime,
                progress: Callable[[str], None] = lambda _: None) -> dict[str, Any]:
    gl = tonight(s, prefix, now)
    legs: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    for i, g in enumerate(gl, 1):
        progress(f"Reading game {i} of {len(gl)}: {g['title']}")
        try:
            d = games.game_detail(s, prefix, g["game_key"])
            cs = candidates(d)[:PER_GAME] if d else []
            if not cs:
                continue
            cmap = {c["ticker"]: c for c in cs}
            ev, _, _ = evidence_for(s, src, [(c["ticker"], side) for c in cs
                                             for side in ("yes", "no")], briefs=True)
            legs += [_leg(lg, cmap[lg["ticker"]], g, prefix) for lg in ev["legs"]
                     if lg.get("brief") and lg["ticker"] in cmap]
        except Exception as e:  # noqa: BLE001 - one bad game doesn't sink the slate
            log.warning("slate: %s failed: %s", g["game_key"], type(e).__name__)
            skipped.append({"game": g["title"], "reason": str(e)[:160]})
    progress("Building combos")
    pool = pick_pool(legs)
    study = latest_study(s)
    combos = [_combo(s, src, c, study) for c in combos_from(pool)]
    leans: dict[str, int] = {}
    for x in legs:
        leans[x["brief"]["lean"]] = leans.get(x["brief"]["lean"], 0) + 1
    return {
        "prefix": prefix, "generated_at": now.isoformat(),
        "games": [{"game_key": g["game_key"], "title": g["title"],
                   "occurs_at": _aware(g["occurs_at"]).isoformat()} for g in gl],
        "combos": combos,
        "pool": [{k: x[k] for k in ("ticker", "side", "label", "bet", "event_ticker", "game",
                                    "price", "brief")} for x in pool],
        "briefed": len(legs), "leans": leans, "skipped": skipped,
        "rules": {"leg_price": [LEG_MIN, LEG_MAX], "min_score": MIN_SCORE,
                  "max_per_game": MAX_PER_GAME},
    }


class SlateRunner:
    """One slate build at a time, in a background thread; the page polls the state."""

    def __init__(self, factory: sessionmaker[Session], now: Callable[[], datetime]) -> None:
        self._factory = factory
        self._now = now
        self._lock = threading.Lock()
        self._state: dict[str, dict[str, Any]] = {}

    def state(self, prefix: str) -> dict[str, Any]:
        with self._lock:
            st = dict(self._state.get(prefix) or {"status": "idle"})
        if st.get("status") == "ready" and st.get("finished_at"):
            st["fresh"] = self._now() - datetime.fromisoformat(st["finished_at"]) < FRESH
        return st

    def start(self, prefix: str, src: EspnSource) -> dict[str, Any]:
        with self._lock:
            if any(v.get("status") == "building" for v in self._state.values()):
                return dict(self._state[next(k for k, v in self._state.items()
                                             if v.get("status") == "building")])
            prev = self._state.get(prefix) or {}
            self._state[prefix] = {"status": "building", "progress": "Starting",
                                   "started_at": self._now().isoformat(),
                                   "result": prev.get("result")}

        def progress(msg: str) -> None:
            with self._lock:
                self._state[prefix]["progress"] = msg

        def run() -> None:
            try:
                with self._factory() as s:
                    res = build_slate(s, src, prefix, self._now(), progress)
                upd = {"status": "ready", "result": res, "error": None}
            except Exception as e:  # noqa: BLE001
                log.exception("slate build failed")
                upd = {"status": "failed", "error": str(e)[:200]}
            with self._lock:
                self._state[prefix].update(upd, finished_at=self._now().isoformat(),
                                           progress=None)

        threading.Thread(target=run, name="slate-build", daemon=True).start()
        return self.state(prefix)
