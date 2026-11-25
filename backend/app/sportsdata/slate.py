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
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from app.catalog import games
from app.catalog.combos import history_for, latest_study
from app.sportsdata.espn import EspnSource
from app.sportsdata.evidence import adjusted_probability
from app.sportsdata.ideas import _family, candidates
from app.sportsdata.service import evidence_for
from app.sportsdata.slate_ai import SlateModel

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
# Model path: a wider net per game, news per game, and a cap on what the final call sees.
WIDE_MIN, WIDE_MAX = 0.30, 0.85
WIDE_PER_GAME = 8
NEWS_PER_GAME = 6               # preview, injuries, then props for the top players
NEWS_PER_QUERY = 4
ASSEMBLE_MAX = 24


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


def valid_combo(legs: Sequence[dict[str, Any]]) -> bool:
    """The hard limits, for rule combos and for anything the model proposes."""
    n = len(legs)
    if not 3 <= n <= 4 or len({x["ticker"] for x in legs}) < n:
        return False
    if len({x["family"] for x in legs}) < n:  # e.g. winner + spread of one game
        return False
    players = [x["subject"] for x in legs if x["kind"] == "player_stat"]
    if len(players) != len(set(players)):
        return False
    per_game: dict[str, int] = {}
    for x in legs:
        per_game[x["game_key"]] = per_game.get(x["game_key"], 0) + 1
    return max(per_game.values()) <= MAX_PER_GAME


def combos_from(pool: list[dict[str, Any]]) -> list[tuple[dict[str, Any], ...]]:
    ranked = []
    for n in (3, 4):
        for legs in itertools.combinations(pool, n):
            if not valid_combo(legs):
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
                                                 "why": x["brief"]["for"][:3],
                                                 "history": x.get("history") or []}
                 for x in legs],
        "games": len({x["game_key"] for x in legs}),
        "market": round(market, 4), "adjusted": round(adj, 4),
        "together": [{"team": c["team"], "lift": c["lift"], "games": c["games"]}
                     for c in together],
        "pays": round(1 / adj, 1) if adj > 0 else None,
        "risks": risks,
        "past": history_for(study, len(legs)),
    }


def wide_pool(legs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One game's candidates for the model: a wider net than clear_case (the model may see
    what the rules can't), best rung per player/team per stat, weak and injured cases out."""
    best: dict[tuple[str, str | None], dict[str, Any]] = {}
    for x in legs:
        b, p = x["brief"], x["price"]
        if (not x["eligible"] or p is None or not WIDE_MIN <= p <= WIDE_MAX
                or b["lean"] in ("avoid", "thin", "weak") or b["score"] < 0):
            continue
        k = (x["event_ticker"], x["subject"])
        cur = best.get(k)
        if cur is None or (b["score"], p) > (cur["brief"]["score"], cur["price"]):
            best[k] = x
    ranked = sorted(best.values(), key=lambda x: (-x["brief"]["score"], abs(x["price"] - 0.55)))
    return ranked[:WIDE_PER_GAME]


def news_queries(names: list[str], cands: list[dict[str, Any]], n: int) -> list[str]:
    """Up to n searches for one game: a preview, the injury news, then one prop search per
    player the candidate legs are about (most legs first: their minutes, role, matchup and
    what prop writers see), or the home team's rotation when there are no player legs."""
    if len(names) < 2 or n <= 0:
        return []
    a, b = names[0], names[1]
    counts: dict[str, int] = {}
    for x in cands:
        if x["kind"] == "player_stat" and x["subject"]:
            counts[x["subject"]] = counts.get(x["subject"], 0) + 1
    players = sorted(counts, key=lambda k: -counts[k])
    qs = [f"{a} vs {b} preview", f"{a} {b} injury report"]
    qs += [f"{who} props" for who in players] or [f"{b} rotation"]
    return qs[:n]


def _game_facts(g: dict[str, Any], cands: list[dict[str, Any]],
                news: list[dict[str, str]]) -> dict[str, Any]:
    def texts(ps: list[dict[str, str]]) -> list[str]:
        return [p["text"][:180] for p in ps[:6]]
    return {
        "game": g["title"], "tip_utc": str(g["occurs_at"]),
        "legs": [{"id": x["id"], "bet": x["bet"], "price": x["price"],
                  "rule_lean": x["brief"]["lean"], "for": texts(x["brief"]["for"]),
                  "against": texts(x["brief"]["against"]),
                  "context": texts(x["brief"]["context"])}
                 | ({"your_history": _hist(x)} if _hist(x) else {}) for x in cands],
        "news": [{k: n[k] for k in ("id", "title", "source", "age", "snippet")} for n in news],
    }


def _hist(x: dict[str, Any], n: int = 3) -> list[str]:
    """This user's own past record on bets like this leg (app.history.legs), as text."""
    return [w["text"][:220] for w in (x.get("history") or [])[:n]]


def attach_history(s: Session, legs: list[dict[str, Any]]) -> list[str]:
    """Warn on legs that repeat your past mistakes; returns your general lessons. Never fatal:
    no synced history just means no warnings."""
    try:
        from sqlalchemy import select

        from app.db.models import CatalogMarket
        from app.history.legs import Warner

        titles = dict(s.execute(select(CatalogMarket.ticker, CatalogMarket.title).where(
            CatalogMarket.ticker.in_([x["ticker"] for x in legs]))).all())
        w = Warner(s)
        for x in legs:
            x["history"] = w.for_leg(x["ticker"], x["side"], titles.get(x["ticker"], ""))
        return [ls.text for ls in w.lessons][:12]
    except Exception:  # noqa: BLE001
        log.warning("slate: history warnings unavailable", exc_info=True)
        return []


def _summary(x: dict[str, Any]) -> dict[str, Any]:
    return {"bet": x["bet"], "game": x["game"], "note": x["review"]["note"],
            "sources": x["review"]["sources"]}


def _model_pass(s: Session, src: EspnSource, gl: list[dict[str, Any]],
                by_game: dict[str, list[dict[str, Any]]], study: dict[str, Any] | None,
                model: SlateModel, news: Callable[[str], list[dict[str, str]]] | None,
                news_per_game: int, progress: Callable[[str], None],
                lessons: list[str] | None = None) -> dict[str, Any]:
    """Per game: candidates + news -> the model's keep/caution/drop. Then one call assembles
    combos from the survivors; code enforces the hard limits and prices them."""
    from app.investigate.ledger import BudgetExhausted

    news_info: dict[str, Any] = {"searched": 0, "items": 0, "status": "ok" if news else "no_key"}
    reviews: list[dict[str, Any]] = []
    all_news: list[dict[str, str]] = []
    reviewed: list[dict[str, Any]] = []
    budget_hit = False
    n_leg = 0
    for i, g in enumerate(gl, 1):
        cands = wide_pool(by_game.get(g["game_key"], []))
        if not cands:
            continue
        for x in cands:
            n_leg += 1
            x["id"] = f"L{n_leg}"
        items: list[dict[str, str]] = []
        if news and not budget_hit:
            progress(f"News for game {i} of {len(gl)}: {g['title']}")
            seen = {n["url"] for n in all_news}
            for q in news_queries(g.get("search_names") or [], cands, news_per_game):
                try:
                    got = news(q)
                except BudgetExhausted as e:
                    budget_hit = True
                    news_info.update(status="budget", message=str(e))
                    break
                except Exception as e:  # noqa: BLE001 - one failed search isn't fatal
                    log.info("slate news search failed: %s", type(e).__name__)
                    continue
                news_info["searched"] += 1
                for it in got[:NEWS_PER_QUERY]:
                    if it["url"] in seen:
                        continue
                    seen.add(it["url"])
                    items.append({**it, "id": f"N{len(all_news) + len(items) + 1}",
                                  "game": g["title"], "query": q})
            all_news += items
        progress(f"Model reviewing game {i} of {len(gl)}: {g['title']}")
        r = model.review_game(_game_facts(g, cands, items), {x["id"] for x in cands},
                              {n["id"] for n in items})
        reviews.append({"game": g["title"], "note": r["game_note"],
                        "news": [n["id"] for n in items]})
        for x in cands:
            x["review"] = r["legs"].get(x["id"]) or {"verdict": "keep", "conflict": False,
                                                    "note": "", "sources": []}
            reviewed.append(x)
    news_info["items"] = len(all_news)

    kept = [x for x in reviewed if x["review"]["verdict"] != "drop"]
    kept.sort(key=lambda x: (x["review"]["verdict"] != "keep", -x["brief"]["score"]))
    kept = kept[:ASSEMBLE_MAX]
    by_id = {x["id"]: x for x in kept}
    combos: list[dict[str, Any]] = []
    summary, declined = "", ""
    if len(kept) >= 3:
        progress("Model assembling combos")
        a = model.assemble({
            "legs": [{"id": x["id"], "game": x["game"], "bet": x["bet"], "price": x["price"],
                      "rule_score": x["brief"]["score"], "verdict": x["review"]["verdict"],
                      "note": x["review"]["note"]}
                     | ({"your_history": _hist(x, 2)} if _hist(x) else {}) for x in kept],
            "your_lessons": (lessons or [])[:12],
            "past_combo_returns": {b["bucket"]: b.get("return_per_dollar")
                                   for b in (study or {}).get("by_legs", [])},
        }, set(by_id))
        summary, declined = a["summary"], a["pass_reason"]
        taken: list[set[str]] = []
        for c in a["combos"]:
            if any(i not in by_id for i in c["legs"]):
                continue  # only legs that survived the review
            chosen = tuple(by_id[i] for i in c["legs"])
            if not valid_combo(chosen) or set(c["legs"]) in taken:
                continue  # the model broke a hard limit: code doesn't trust it
            taken.append(set(c["legs"]))
            combos.append(_combo(s, src, chosen, study) | {
                "source": "model", "case": c["case"], "risk": c["risk"]})
            if len(combos) >= MAX_COMBOS:
                break
    else:
        declined = "Fewer than 3 legs survived the review."
    return {
        "combos": combos, "summary": summary, "pass_reason": declined, "reviews": reviews,
        "dropped": [_summary(x) for x in reviewed if x["review"]["verdict"] == "drop"],
        "conflicts": [_summary(x) for x in reviewed if x["review"]["conflict"]],
        "news": all_news, "news_info": news_info,
    }


def build_slate(s: Session, src: EspnSource, prefix: str, now: datetime,
                progress: Callable[[str], None] = lambda _: None,
                news: Callable[[str], list[dict[str, str]]] | None = None,
                model: SlateModel | None = None, model_off: str | None = None,
                news_per_game: int = NEWS_PER_GAME) -> dict[str, Any]:
    """news(query) -> items (raises BudgetExhausted to stop). model None -> rules only, with
    model_off saying why. A model failure falls back to the rules and says so."""
    gl = tonight(s, prefix, now)
    legs: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    by_game: dict[str, list[dict[str, Any]]] = {}
    for i, g in enumerate(gl, 1):
        progress(f"Reading game {i} of {len(gl)}: {g['title']}")
        try:
            d = games.game_detail(s, prefix, g["game_key"])
            cs = candidates(d)[:PER_GAME] if d else []
            if not cs:
                continue
            g["search_names"] = _search_names(src, prefix, g)
            cmap = {c["ticker"]: c for c in cs}
            ev, _, _ = evidence_for(s, src, [(c["ticker"], side) for c in cs
                                             for side in ("yes", "no")], briefs=True)
            mine = [_leg(lg, cmap[lg["ticker"]], g, prefix) for lg in ev["legs"]
                    if lg.get("brief") and lg["ticker"] in cmap]
            legs += mine
            by_game[g["game_key"]] = mine
        except Exception as e:  # noqa: BLE001 - one bad game doesn't sink the slate
            log.warning("slate: %s failed: %s", g["game_key"], type(e).__name__)
            skipped.append({"game": g["title"], "reason": str(e)[:160]})

    lessons = attach_history(s, legs)
    study = latest_study(s)
    pool = pick_pool(legs)
    rule_combos = [_combo(s, src, c, study) | {"source": "rules"} for c in combos_from(pool)]
    engine: dict[str, Any] = {"mode": "rules", "model": None, "seconds": 0.0,
                              "reason": model_off}
    out: dict[str, Any] = {"combos": rule_combos, "summary": "", "pass_reason": "",
                           "reviews": [], "dropped": [], "conflicts": [], "news": [],
                           "news_info": {"searched": 0, "items": 0, "status": "off"}}
    if model is not None:
        try:
            out = _model_pass(s, src, gl, by_game, study, model, news, news_per_game, progress,
                              lessons)
            engine = {"mode": "local_model", "model": model.model,
                      "seconds": round(model.seconds, 1), "reason": None}
        except Exception as e:  # noqa: BLE001 - fall back to the rules, and say why
            log.warning("slate model failed: %s", type(e).__name__)
            engine = {"mode": "rules", "model": model.model, "seconds": 0.0,
                      "reason": f"The local model failed ({str(e)[:160]}); showing rule-only "
                                "combos"}
    leans: dict[str, int] = {}
    for x in legs:
        leans[x["brief"]["lean"]] = leans.get(x["brief"]["lean"], 0) + 1
    return {
        "prefix": prefix, "generated_at": now.isoformat(),
        "games": [{"game_key": g["game_key"], "title": g["title"],
                   "occurs_at": _aware(g["occurs_at"]).isoformat()} for g in gl],
        "engine": engine, "summary": out["summary"], "pass_reason": out["pass_reason"],
        "combos": out["combos"],
        "rule_combos": rule_combos if engine["mode"] == "local_model" else [],
        "reviews": out["reviews"], "dropped": out["dropped"], "conflicts": out["conflicts"],
        "news": [{k: n[k] for k in ("id", "game", "title", "source", "age", "url")}
                 for n in out["news"]],
        "news_info": out["news_info"],
        "pool": [{k: x[k] for k in ("ticker", "side", "label", "bet", "event_ticker", "game",
                                    "price", "brief")} | {"history": x.get("history") or []}
                 for x in pool],
        "history_flags": sum(1 for x in legs if x.get("history")),
        "lessons": lessons,
        "briefed": len(legs), "leans": leans, "skipped": skipped,
        "rules": {"leg_price": [LEG_MIN, LEG_MAX], "min_score": MIN_SCORE,
                  "max_per_game": MAX_PER_GAME},
    }


def _search_names(src: EspnSource, prefix: str, g: dict[str, Any]) -> list[str]:
    """Full team names for news searches ('Detroit Pistons'), away team first."""
    from app.sportsdata.espn import LEAGUES as ESPN_LEAGUES

    league = ESPN_LEAGUES.get(prefix)
    names = []
    for t in g.get("teams") or []:
        try:
            ref = src.team(league, t["code"], t["name"]) if league else None
        except Exception:  # noqa: BLE001
            ref = None
        names.append(ref["name"] if ref else t["name"])
    return names


Helpers = tuple["SlateModel | None", "str | None",
                "Callable[[str], list[dict[str, str]]] | None", "Callable[[], None]"]


class SlateRunner:
    """One slate build at a time, in a background thread; the page polls the state.

    `helpers()` runs inside the thread and returns (model or None, why the model is off,
    news(query) or None, close). Opening Ollama and the news client there keeps the request
    instant."""

    def __init__(self, factory: sessionmaker[Session], now: Callable[[], datetime]) -> None:
        self._factory = factory
        self._now = now
        self._lock = threading.Lock()
        self._state: dict[str, dict[str, Any]] = {}
        self.news_per_game = NEWS_PER_GAME

    def state(self, prefix: str) -> dict[str, Any]:
        with self._lock:
            st = dict(self._state.get(prefix) or {"status": "idle"})
        if st.get("status") == "ready" and st.get("finished_at"):
            st["fresh"] = self._now() - datetime.fromisoformat(st["finished_at"]) < FRESH
        return st

    def start(self, prefix: str, src: EspnSource,
              helpers: Callable[[], Helpers] | None = None) -> dict[str, Any]:
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
            model, off, news, close = (helpers() if helpers else
                                       (None, "The local model isn't set up", None, lambda: None))
            try:
                with self._factory() as s:
                    res = build_slate(s, src, prefix, self._now(), progress, news=news,
                                      model=model, model_off=off,
                                      news_per_game=self.news_per_game)
                upd = {"status": "ready", "result": res, "error": None}
            except Exception as e:  # noqa: BLE001
                log.exception("slate build failed")
                upd = {"status": "failed", "error": str(e)[:200]}
            finally:
                close()
            with self._lock:
                self._state[prefix].update(upd, finished_at=self._now().isoformat(),
                                           progress=None)

        threading.Thread(target=run, name="slate-build", daemon=True).start()
        return self.state(prefix)


class NewsCache:
    """Brave results per query for a few hours, so a rebuild doesn't pay twice."""

    def __init__(self, hours: float, now: Callable[[], datetime]) -> None:
        self._ttl = timedelta(hours=hours)
        self._now = now
        self._lock = threading.Lock()
        self._hits: dict[str, tuple[datetime, list[dict[str, str]]]] = {}

    def get(self, q: str, fetch: Callable[[str], list[dict[str, str]]]
            ) -> list[dict[str, str]]:
        with self._lock:
            hit = self._hits.get(q.lower())
            if hit and self._now() - hit[0] < self._ttl:
                return hit[1]
        items = fetch(q)
        with self._lock:
            self._hits[q.lower()] = (self._now(), items)
        return items
