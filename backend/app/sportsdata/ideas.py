"""Bet ideas for one game: screen every liquid leg against box-score history and the order
book, then build small combos only from legs that stand on their own.

Deterministic, no AI. What each data source can and can't do:
- Kalshi alone (prices, spread, fees) can't say which side is likelier: the price IS the
  market's estimate. It can say how to get in cheaper: rest a limit order instead of paying
  the ask plus the taker fee. Those are "entries".
- History (ESPN box scores) is what can disagree with the price. A leg only becomes an idea
  when its history-based estimate beats the all-in price (ask + fee).
Ideas are things to research, ranked by numbers, never instructions to bet.
"""

from __future__ import annotations

import itertools
import math
from decimal import ROUND_FLOOR, Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.catalog import games
from app.catalog.combos import history_for, latest_study
from app.catalog.slipcheck import CENT, Fees, _side_prices, price_single, walk_away
from app.db.models import AccountPosition, CatalogEvent, CatalogMarket
from app.sportsdata.espn import EspnSource
from app.sportsdata.evidence import adjusted_probability, avg_text
from app.sportsdata.service import evidence_for

MIN_MID, MAX_MID = 0.10, 0.90   # skip near-locks and lottery tickets
MAX_CANDIDATES = 90
MIN_EDGE_PTS = 2.0               # history must beat the all-in price by 2 pts
POOL = 8                         # best legs considered for combos
MAX_COMBOS = 4
ENTRY_MIN_SPREAD = Decimal("0.03")
OUT = ("out", "doubtful")
ROLE_CHANGE = 3                  # props of one player leaning the same way against history


def _family(prefix: str, event_ticker: str) -> str:
    """Legs in one family overlap logically: winner and spread both decide who wins (a 6+
    point win IS a win), so a combo takes at most one of them."""
    series, _, key = event_ticker.partition("-")
    return f"outcome:{key}" if series in (f"{prefix}GAME", f"{prefix}SPREAD") else event_ticker


def flag_role_changes(singles: list[dict[str, Any]]) -> None:
    """When the market prices several of one player's props the same way against his history
    (all unders, or all overs), it usually knows something box scores don't yet: a starter
    out, a minutes limit. Demote those legs and say why. Counts distinct props, not rungs."""
    lean_of: dict[tuple[str, str], set[str]] = {}
    for x in singles:
        if x["kind"] == "player_stat" and x["subject"]:
            lean_of.setdefault((x["subject"], x["side"]), set()).add(x["event_ticker"])
    for x in singles:
        n = len(lean_of.get((x["subject"], x["side"]), ()))
        if x["kind"] == "player_stat" and n >= ROLE_CHANGE:
            more = "bigger" if x["side"] == "no" else "smaller"
            x["strength"] = "lean"
            x["caution"] = (f"The market disagrees with his history on {n} props, all the same "
                            f"way: likely a {more} role tonight. History may be stale.")


def _d(x: float | None) -> Decimal | None:
    return None if x is None else Decimal(str(round(float(x), 4)))


def candidates(detail: dict[str, Any]) -> list[dict[str, Any]]:
    """Liquid full-game legs from a game_detail: game lines and player props."""
    out: list[dict[str, Any]] = []
    for sec in detail["sections"]:
        if sec["id"] != "main":
            continue
        for g in sec["groups"]:
            out += [{**c, "group": g["label"], "eligible": g["eligible"]} for c in g["markets"]]
    for p in detail["players"]:
        for st in p["stats"].values():
            out += [{**c, "group": f"{p['name']} {st['label'].lower()}",
                     "eligible": st["eligible"]} for c in st["markets"]]
    keep = [c for c in out if c["yes_bid"] and c["yes_ask"] and c["implied"] is not None
            and MIN_MID <= c["implied"] <= MAX_MID]
    keep.sort(key=lambda c: -c["volume_24h"])
    return keep[:MAX_CANDIDATES]


def _cap(s: Session, budget: Decimal | None, fraction: Decimal, unset: Decimal
         ) -> tuple[Decimal, Decimal]:
    cap = (budget * fraction).quantize(CENT) if budget else unset
    open_cost = sum((p.exposure for p in s.scalars(select(AccountPosition)) if p.position != 0),
                    Decimal(0))
    return cap, open_cost


def _contracts(cap: Decimal, price: Decimal) -> int:
    return int((cap / price).to_integral_value(rounding=ROUND_FLOOR)) if price > 0 else 0


def build_ideas(s: Session, src: EspnSource | None, prefix: str, key: str,
                budget: Decimal | None, fraction: Decimal, unset_cap: Decimal
                ) -> dict[str, Any] | None:
    detail = games.game_detail(s, prefix, key)
    if detail is None:
        return None
    fees = Fees(s)
    cap, open_cost = _cap(s, budget, fraction, unset_cap)
    cands = candidates(detail)

    evidence: dict[str, dict[str, Any]] = {}
    evidence_error = None
    if src is not None and cands:
        try:
            ev, _, _ = evidence_for(s, src, [(c["ticker"], "yes") for c in cands])
            evidence = {lg["ticker"]: lg for lg in ev["legs"]}
        except Exception as e:  # noqa: BLE001 - ideas fall back to entries only
            evidence_error = str(e)[:200]

    singles: list[dict[str, Any]] = []
    entries: list[dict[str, Any]] = []
    skipped = {"thin": 0, "injured": 0, "no_history": 0, "priced_right": 0}
    series_of: dict[str, str] = {}
    for c in cands:
        m = s.get(CatalogMarket, c["ticker"])
        if m is None:
            continue
        e = s.get(CatalogEvent, m.event_ticker)
        series = e.series_ticker if e else c["ticker"].split("-")[0]
        series_of[c["ticker"]] = series
        y = Decimal(str(c["implied"]))
        lg = evidence.get(c["ticker"]) or {}
        sup = bool(lg.get("supported"))
        best: dict[str, Any] | None = None
        for side in ("yes", "no"):
            ask, bid = _side_prices(m, side)
            mid = y if side == "yes" else 1 - y
            hist = None
            if sup:
                est = float(lg["estimate"])
                hist = _d(est if side == "yes" else 1 - est)
            item = price_single(fees, {"ticker": c["ticker"], "side": side, "label": c["title"],
                                       "series": series, "mid": mid, "ask": ask, "bid": bid,
                                       "history": hist, "p_est": hist})
            item["bet"] = f"{side.upper()} · {c['group']} {c['label']}".strip()
            # Kalshi-only: a cheaper entry exists when the spread is wide and resting is cheap.
            # Priced from the book alone (no history ceiling), so the saving is real.
            if ask is not None and bid is not None and ask - bid >= ENTRY_MIN_SPREAD:
                book = price_single(fees, {**item, "series": series, "mid": mid, "ask": ask,
                                           "bid": bid, "history": None, "p_est": None})
                if lim := book.get("limit"):
                    entries.append({"ticker": c["ticker"], "side": side, "bet": item["bet"],
                                    "ask": book["ask"], "bid": book["bid"],
                                    "limit": lim["price"], "saves_per_100": lim["saves_per_100"],
                                    "maker_fee_per_100": lim["maker_fee_per_100"],
                                    "mid": str(mid)})
            if hist is not None and item.get("edge_pts") is not None and (
                    best is None or item["edge_pts"] > best["edge_pts"]):
                lo, hi = lg["interval"]
                item["interval"] = [lo, hi] if side == "yes" else [round(1 - hi, 4),
                                                                   round(1 - lo, 4)]
                best = item
        if not sup:
            skipped["no_history"] += 1
            continue
        if lg.get("verdict") == "thin":
            skipped["thin"] += 1
            continue
        inj = lg.get("injury")
        if inj and any(w in inj["status"].lower() for w in OUT):
            skipped["injured"] += 1
            continue
        if best is None or best["edge_pts"] < MIN_EDGE_PTS:
            skipped["priced_right"] += 1
            continue
        clears = Decimal(str(best["interval"][0])) > Decimal(best["all_in"])
        price = Decimal(best["limit"]["price"]) if best.get("limit") else Decimal(best["ask"])
        best.update({
            "strength": "strong" if clears else "lean",
            "event_ticker": c["event_ticker"], "eligible": c["eligible"],
            "subject": (lg.get("subject") or {}).get("name"), "kind": lg.get("kind"),
            "family": _family(prefix, c["event_ticker"]), "caution": None,
            "windows": lg.get("windows"), "season_avg": lg.get("season_avg"),
            "season_avg_text": avg_text(lg),
            "team": (lg.get("subject") or {}).get("team"),
            "line": lg.get("line"), "injury": inj,
            "contracts_at_cap": _contracts(cap, price),
        })
        singles.append(best)

    flag_role_changes(singles)
    singles.sort(key=lambda x: (x["caution"] is not None, x["strength"] != "strong",
                                -x["edge_pts"]))
    # One rung per ladder: the best line for each player/team in each market family.
    rung: set[tuple[str, str | None]] = set()
    singles = [x for x in singles if not ((x["event_ticker"], x["subject"]) in rung
                                          or rung.add((x["event_ticker"], x["subject"])))]
    entries.sort(key=lambda x: -float(x["saves_per_100"] or 0))
    once: set[str] = set()  # one entry per market: the side with the bigger saving
    entries = [x for x in entries if not (x["ticker"] in once or once.add(x["ticker"]))]
    for i, x in enumerate(singles, 1):
        x["id"] = f"S{i}"

    # --- combos from legs that stand alone ------------------------------------------------
    pool: list[dict[str, Any]] = []
    seen: set[tuple[str, str | None]] = set()
    for x in singles:
        k = (x["event_ticker"], x["subject"])  # one line per player/team per stat
        if x["eligible"] and x["caution"] is None and k not in seen:
            seen.add(k)
            pool.append(x)
        if len(pool) >= POOL:
            break
    rough = []
    for n in (2, 3):
        for legs in itertools.combinations(pool, n):
            if len({x["family"] for x in legs}) < n:
                continue  # e.g. winner + spread: the second leg mostly repeats the first
            fair = math.prod(float(x["mid"]) for x in legs)
            hist = math.prod(float(x["history"]) for x in legs)
            rough.append((hist / fair if fair else 0, legs))
    rough.sort(key=lambda t: -t[0])
    combos = []
    study = latest_study(s)
    for _, legs in rough[:MAX_COMBOS * 2]:
        mids = {x["ticker"]: float(x["mid"]) for x in legs}
        hist = math.prod(float(x["history"]) for x in legs)
        lift = None
        if src is not None:
            try:
                ev, _, _ = evidence_for(s, src, [(x["ticker"], x["side"]) for x in legs])
                lifts = [c["lift"] for c in ev["correlation"] if c.get("lift")]
                lift = math.prod(lifts) if lifts else None
            except Exception:  # noqa: BLE001
                lift = None
        corr = [{"lift": lift}] if lift else []
        p = adjusted_probability(hist, corr,
                                 {x["ticker"]: float(x["history"]) for x in legs}) or hist
        # Market side gets the same correlation, so the ratio reflects leg edges, not the
        # (real) fact that same-team legs land together.
        fair = adjusted_probability(math.prod(mids.values()), corr, mids) or 0.0
        wa = walk_away(Decimal(str(p)), fees, "KXMVECROSSCATEGORY")
        combos.append({"legs": [x["id"] for x in legs], "tickers": [x["ticker"] for x in legs],
                       "bets": [x["bet"] for x in legs], "sides": [x["side"] for x in legs],
                       "fair": round(fair, 4), "history": round(p, 4),
                       "lift": None if lift is None else round(lift, 3),
                       "walk_away": None if wa is None else str(wa),
                       "ratio": round(p / fair, 2) if fair else None,
                       "past": history_for(study, len(legs))})
    combos.sort(key=lambda c: -(c["ratio"] or 0))
    combos = combos[:MAX_COMBOS]
    for i, c in enumerate(combos, 1):
        c["id"] = f"K{i}"

    return {
        "game": {"prefix": prefix, "game_key": key, "title": detail["title"],
                 "occurs_at": detail["occurs_at"]},
        "singles": singles[:10], "combos": combos, "entries": entries[:6],
        "screened": len(cands), "skipped": skipped,
        "evidence_enabled": src is not None, "evidence_error": evidence_error,
        "cap": str(cap), "open_cost": str(open_cost.quantize(CENT)),
        "budget": None if budget is None else str(budget),
        "fees_verified": fees.verified,
    }


def ideas_facts(ideas: dict[str, Any], heads: list[dict[str, str]]) -> dict[str, Any]:
    """What the model sees: the screened candidates only, compacted."""
    return {
        "game": ideas["game"]["title"],
        "budget": {"per_idea_cap": ideas["cap"], "already_open": ideas["open_cost"],
                   "total_budget": ideas["budget"]},
        "singles": [{k: x.get(k) for k in ("id", "bet", "team", "ask", "all_in", "history",
                                           "interval", "edge_pts", "strength", "windows",
                                           "line", "contracts_at_cap", "caution")}
                    | {"season_average": x.get("season_avg_text")}
                    | {"limit": (x.get("limit") or {}).get("price"),
                       "injury": None if not x.get("injury") else
                       f"{x['injury']['status']}: {x['injury']['detail']}"[:200]}
                    for x in ideas["singles"]],
        "combos": [{k: c.get(k) for k in ("id", "legs", "fair", "history", "lift", "walk_away",
                                          "ratio")}
                   | {"past_combos_this_size": (c.get("past") or {}).get("return_per_dollar")}
                   for c in ideas["combos"]],
        "headlines": [{k: h[k] for k in ("id", "about", "title", "source", "age", "snippet")}
                      for h in heads],
        "screened": ideas["screened"], "skipped": ideas["skipped"],
    }
