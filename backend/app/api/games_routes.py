"""Games page: one game per screen, plus outside evidence for the legs in a combo.

GETs, plus one POST (the optional, paid AI review). Prices come from the local catalog
(last scan). Evidence calls ESPN's public JSON (no key) and, only if keys are configured,
a headline search and OpenAI. Nothing is traded.
"""

from __future__ import annotations

import re
from datetime import UTC, timedelta
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Header, Path, Query, Request
from pydantic import BaseModel
from pydantic import Field as PydField

from app.adapters.base import AdapterError
from app.api.errors import ApiError, ErrorCode
from app.api.routes import ClockDep, SessionDep, SettingsDep
from app.catalog import games
from app.catalog.slipcheck import check_slip
from app.investigate.ledger import BudgetExhausted, record_hook
from app.sportsdata.espn import COLLEGE, LEAGUES, EspnSource
from app.sportsdata.evidence import avg_text
from app.sportsdata.ideas import build_ideas, ideas_facts
from app.sportsdata.llm import LlmError, llm_status, local_reviewer, make_reviewer
from app.sportsdata.news import NewsSearch, headlines
from app.sportsdata.service import evidence_for

router = APIRouter(prefix="/api/games")

Prefix = Annotated[str, Path(pattern=games.PREFIX.pattern, max_length=24)]
Key = Annotated[str, Path(pattern=games.GAME_KEY.pattern, max_length=40)]
League = Annotated[str | None, Query(pattern=r"^[A-Z0-9]{2,20}$")]
PAST_GRACE = timedelta(hours=5)  # a game that started more than 5h ago is over


def _espn(request: Request, enabled: bool) -> EspnSource:
    if not enabled:
        raise ApiError(409, ErrorCode.SOURCE_FAILURE,
                       "Outside evidence is switched off (KRT_SPORTS_EVIDENCE_ENABLED=false)")
    src = getattr(request.app.state, "espn", None)
    if src is None:
        src = request.app.state.espn = EspnSource(
            min_interval=request.app.state.settings.espn_min_request_interval_seconds)
    return src


def _legs(raw: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for part in raw.split(","):
        t, _, side = part.strip().rpartition(":")
        if not games.TICKER_RE.match(t) or side not in ("yes", "no"):
            raise ApiError(422, ErrorCode.VALIDATION_ERROR, f"Bad leg {part[:60]!r}")
        out.append((t, side))
    if not 1 <= len(out) <= 12:
        raise ApiError(422, ErrorCode.VALIDATION_ERROR, "Use 1 to 12 legs")
    return out


@router.get("")
def list_games(session: SessionDep, clock: ClockDep, league: League = None,
               include_past: bool = False) -> dict[str, Any]:
    out = games.list_games(session, league)
    if not include_past:
        cutoff = clock.now() - PAST_GRACE

        def upcoming(g: dict[str, Any]) -> bool:
            t = g["occurs_at"]
            if t is None:
                return True
            return (t if t.tzinfo else t.replace(tzinfo=UTC)) >= cutoff
        out["items"] = [g for g in out["items"] if upcoming(g)]
    return out


def _evidence(session: Any, settings: Any, request: Request,
              parsed: list[tuple[str, str]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    src = _espn(request, settings.sports_evidence_enabled)
    out, rows, missing = evidence_for(session, src, parsed)
    if missing:
        raise ApiError(404, ErrorCode.NOT_FOUND, f"{missing[0]} is not in the catalog")
    return out, rows


@router.get("/evidence")
def leg_evidence(session: SessionDep, settings: SettingsDep, request: Request,
                 legs: Annotated[str, Query(min_length=3, max_length=2000)]) -> dict[str, Any]:
    return _evidence(session, settings, request, _legs(legs))[0]


class NewsIn(BaseModel):
    q: str = PydField(min_length=2, max_length=120)


NEWS_TTL = timedelta(minutes=30)


@router.post("/news")
def news(body: NewsIn, settings: SettingsDep, clock: ClockDep, request: Request,
         x_krt_request: Annotated[str | None, Header(alias="X-KRT-Request")] = None
         ) -> dict[str, Any]:
    """"Headlines here": one Brave request, counted against the app-wide cap. POST + custom
    header, so only a click in this app can spend it (not a link or page on another site)."""
    if x_krt_request != "research":
        raise ApiError(403, ErrorCode.VALIDATION_ERROR, "Missing X-KRT-Request header")
    key = settings.brave_search_api_key
    if key is None:
        return {"configured": False, "items": []}
    clean = re.sub(r"[^\w\s.'+-]", " ", body.q).strip()
    now = clock.now()
    # In-memory only (Brave's terms allow transient storage); a repeat click is free.
    cache = request.app.state.__dict__.setdefault("news_cache", {})
    hit = cache.get(clean.lower())
    if hit and now - hit[0] < NEWS_TTL:
        return {"configured": True, "items": hit[1], "cached": True}
    client = NewsSearch(key.get_secret_value(), timeout=settings.http_timeout_seconds,
                        on_attempt=record_hook(request.app.state, "news", clean))
    try:
        items = client.search(clean)
    except BudgetExhausted as e:
        raise ApiError(429, ErrorCode.VALIDATION_ERROR,
                       f"{e}: no headline search was sent. It resets with the day or month "
                       "(KRT_RESEARCH_BRAVE_*_REQUEST_CAP).") from e
    except AdapterError as e:
        raise ApiError(502, ErrorCode.SOURCE_FAILURE, f"Headline search: {e}") from e
    finally:
        client.close()
    if len(cache) > 200:
        cache.clear()
    cache[clean.lower()] = (now, items)
    return {"configured": True, "items": items, "cached": False}


# --- Slip check: does this combo make sense for your money? -----------------------------------

@router.get("/check")
def slip_check(session: SessionDep, settings: SettingsDep, request: Request,
               legs: Annotated[str, Query(min_length=3, max_length=2000)],
               stake: Annotated[Decimal | None, Query(gt=0, le=1000, max_digits=7,
                                                      decimal_places=2)] = None,
               quote: Annotated[Decimal | None, Query(gt=0, lt=1, max_digits=4,
                                                      decimal_places=2)] = None
               ) -> dict[str, Any]:
    parsed = _legs(legs)
    evidence = None
    if settings.sports_evidence_enabled:
        try:
            evidence, _ = _evidence(session, settings, request, parsed)
        except ApiError as e:
            if e.status == 404:
                raise
        except Exception:  # noqa: BLE001 - outside evidence is optional here
            evidence = None
    return check_slip(session, parsed, evidence, stake, quote,
                      settings.experiment_budget_dollars, settings.scanner_conditional_fraction,
                      settings.scanner_unset_budget_cap)


# --- AI second opinion (optional, paid, on demand) -------------------------------------------

class ReviewLeg(BaseModel):
    ticker: str = PydField(pattern=games.TICKER_RE.pattern, max_length=160)
    side: str = PydField(pattern=r"^(yes|no)$")


class ReviewIn(BaseModel):
    legs: list[ReviewLeg] = PydField(min_length=1, max_length=12)
    quote_cents: int | None = PydField(default=None, ge=1, le=99)


REVIEW_TTL = timedelta(minutes=15)


def _review_state(request: Request) -> dict[str, Any]:
    st = getattr(request.app.state, "review", None)
    if st is None:
        st = request.app.state.review = {"day": None, "count": 0, "cache": {}}
    return st


@router.get("/review/status")
def review_status(settings: SettingsDep, clock: ClockDep, request: Request) -> dict[str, Any]:
    st = _review_state(request)
    today = clock.now().date().isoformat()
    return {**llm_status(settings),
            "used_today": st["count"] if st["day"] == today else 0,
            "daily_cap": settings.llm_max_reviews_per_day if settings.llm_provider == "openai"
            else None,
            "headlines": settings.brave_search_api_key is not None}


@router.post("/review")
def review(body: ReviewIn, session: SessionDep, settings: SettingsDep, clock: ClockDep,
           request: Request,
           x_krt_request: Annotated[str | None, Header(alias="X-KRT-Request")] = None
           ) -> dict[str, Any]:
    # POST + custom header: a page on another site can't make you spend API credit.
    if x_krt_request != "review":
        raise ApiError(403, ErrorCode.VALIDATION_ERROR, "Missing X-KRT-Request header")
    if settings.llm_provider == "openai" and settings.openai_api_key is None:
        raise ApiError(409, ErrorCode.SOURCE_FAILURE,
                       "AI review is off: add an OpenAI key to .env, or use Ollama (see README)")
    parsed = [(lg.ticker, lg.side) for lg in body.legs]
    st = _review_state(request)
    now = clock.now()
    ck = (tuple(parsed), body.quote_cents)
    hit = st["cache"].get(ck)
    if hit and now - hit[0] < REVIEW_TTL:
        return {**hit[1], "cached": True}
    today = now.date().isoformat()
    if st["day"] != today:
        st.update(day=today, count=0, cache={})
    paid = settings.llm_provider == "openai"
    if paid and st["count"] >= settings.llm_max_reviews_per_day:
        raise ApiError(429, ErrorCode.VALIDATION_ERROR,
                       f"Daily AI review cap reached ({settings.llm_max_reviews_per_day}); "
                       "raise KRT_LLM_MAX_REVIEWS_PER_DAY to allow more")
    try:
        ev, rows = _evidence(session, settings, request, parsed)
    except ApiError as e:
        if e.status == 404:
            raise
        ev, rows = {"legs": [], "correlation": [], "independent_probability": None,
                    "adjusted_probability": None}, [{"ticker": t, "side": s, "label": t,
                                                     "implied": None} for t, s in parsed]
    subjects = list(dict.fromkeys(lg["subject"]["name"] for lg in ev["legs"]
                                  if lg.get("supported") and lg.get("subject")))
    heads = headlines(settings, subjects, on_attempt=record_hook(request.app.state, "headlines"))
    by_ticker = {lg["ticker"]: lg for lg in ev["legs"]}

    def leg_facts(r: dict[str, Any]) -> dict[str, Any]:
        e = by_ticker.get(r["ticker"], {})
        p = r.get("implied")
        price = None if p is None else round(p if r["side"] == "yes" else 1 - p, 4)
        f = {"ticker": r["ticker"], "bet": f"{r['side'].upper()} on: {r['label']}",
             "market_probability": price}
        if e.get("supported"):
            f.update({k: e.get(k) for k in ("windows", "estimate", "interval", "verdict",
                                            "line", "injury")})
            f["season_average"] = avg_text(e)
            f["last_games"] = [{"date": g["date"], "opp": g["opponent"], "value": g["value"],
                                "hit": g["hit"]} for g in (e.get("recent") or [])]
        elif e:
            f["evidence"] = f"none ({e.get('reason')})"
        return f

    facts = {
        "legs": [leg_facts(r) for r in rows],
        "combo": {"independent_probability": ev.get("independent_probability"),
                  "history_adjusted_probability": ev.get("adjusted_probability"),
                  "kalshi_quote": None if body.quote_cents is None else body.quote_cents / 100,
                  "same_team_correlation": ev.get("correlation")},
        "headlines": [{k: h[k] for k in ("id", "about", "title", "source", "age", "snippet")}
                      for h in heads],
        "today": today,
    }
    chk = check_slip(session, parsed, ev, None,
                     None if body.quote_cents is None else Decimal(body.quote_cents) / 100,
                     settings.experiment_budget_dollars, settings.scanner_conditional_fraction,
                     settings.scanner_unset_budget_cap)
    facts["deterministic_check"] = {
        "verdict": chk["verdict"], "reasons": [r["text"] for r in chk["reasons"]],
        "walk_away_price": chk["combo"]["walk_away"], "sizing": chk["sizing"],
        "singles": [{k: x.get(k) for k in ("label", "side", "ask", "history", "edge_pts",
                                           "value", "limit")} for x in chk["singles"]],
        "trim": chk["trim"]}
    try:
        reviewer = make_reviewer(settings)
    except LlmError as e:
        raise ApiError(409, ErrorCode.SOURCE_FAILURE, str(e)) from e
    try:
        st["count"] += 1  # count attempts, so a failing key can't loop up a bill
        out = reviewer.review(facts, [t for t, _ in parsed], {h["id"] for h in heads})
    except LlmError as e:
        raise ApiError(502, ErrorCode.SOURCE_FAILURE, str(e)) from e
    finally:
        reviewer.close()
    out["sources"] = [{k: h[k] for k in ("id", "title", "source", "age", "url")} for h in heads]
    out["generated_at"] = now.isoformat()
    st["cache"][ck] = (now, out)
    return {**out, "cached": False}


# Parameterized game routes last, so fixed paths like /review/status match first.

@router.get("/{prefix}/{key}")
def game(prefix: Prefix, key: Key, session: SessionDep, protected: bool = False
         ) -> dict[str, Any]:
    out = games.game_detail(session, prefix, key, protected)
    if out is None:
        raise ApiError(404, ErrorCode.NOT_FOUND, "Game not in the catalog (finished, or not "
                       "scanned yet)")
    out["evidence_supported"] = prefix in LEAGUES
    return out


IDEAS_TTL = timedelta(minutes=10)


def _ideas(session: Any, settings: Any, request: Request, clock: Any, prefix: str, key: str
           ) -> dict[str, Any]:
    """Screened ideas for a game, cached per game for 10 minutes (ESPN-heavy)."""
    cache = getattr(request.app.state, "ideas_cache", None)
    if cache is None:
        cache = request.app.state.ideas_cache = {}
    now = clock.now()
    hit = cache.get((prefix, key))
    if hit and now - hit[0] < IDEAS_TTL:
        return hit[1]
    src = _espn(request, True) if settings.sports_evidence_enabled else None
    out = build_ideas(session, src, prefix, key, settings.experiment_budget_dollars,
                      settings.scanner_conditional_fraction, settings.scanner_unset_budget_cap)
    if out is None:
        raise ApiError(404, ErrorCode.NOT_FOUND, "Game not in the catalog")
    out["generated_at"] = now.isoformat()
    cache[(prefix, key)] = (now, out)
    return out


@router.get("/{prefix}/{key}/ideas")
def ideas(prefix: Prefix, key: Key, session: SessionDep, settings: SettingsDep,
          clock: ClockDep, request: Request) -> dict[str, Any]:
    """Deterministic: legs where history beats the all-in price, small combos built only
    from those, and cheaper limit entries. Suggestions to research; nothing is traded."""
    return _ideas(session, settings, request, clock, prefix, key)


@router.post("/{prefix}/{key}/ideas/ai")
def ideas_ai(prefix: Prefix, key: Key, session: SessionDep, settings: SettingsDep,
             clock: ClockDep, request: Request,
             x_krt_request: Annotated[str | None, Header(alias="X-KRT-Request")] = None
             ) -> dict[str, Any]:
    """The local model picks at most 3 ideas FROM the screened list (or passes)."""
    if x_krt_request != "review":
        raise ApiError(403, ErrorCode.VALIDATION_ERROR, "Missing X-KRT-Request header")
    base = _ideas(session, settings, request, clock, prefix, key)
    st = _review_state(request)
    ck = ("ideas", prefix, key, base["generated_at"])
    now = clock.now()
    hit = st["cache"].get(ck)
    if hit and now - hit[0] < REVIEW_TTL:
        return {**hit[1], "cached": True}
    if not base["singles"]:
        return {"summary": "Nothing in this game passed the screen, so there is nothing for "
                "the model to choose from. Passing is the default.", "picks": [], "skip": [],
                "model": None, "seconds": 0, "sources": [], "generated_at": now.isoformat(),
                "cached": False}
    try:
        reviewer = local_reviewer(settings)
    except LlmError as e:
        raise ApiError(409, ErrorCode.SOURCE_FAILURE, str(e)) from e
    subjects = list(dict.fromkeys(x["subject"] for x in base["singles"] if x.get("subject")))
    heads = headlines(settings, subjects, prefix="H", per=2, limit=4,
                      on_attempt=record_hook(request.app.state, "headlines"))
    ids = {x["id"] for x in base["singles"]} | {c["id"] for c in base["combos"]}
    try:
        out = reviewer.ideas(ideas_facts(base, heads), ids, {h["id"] for h in heads},
                             float(base["cap"]))
    except LlmError as e:
        raise ApiError(502, ErrorCode.SOURCE_FAILURE, str(e)) from e
    finally:
        reviewer.close()
    out["sources"] = [{k: h[k] for k in ("id", "title", "source", "age", "url")} for h in heads]
    out["generated_at"] = now.isoformat()
    st["cache"][ck] = (now, out)
    return {**out, "cached": False}


@router.get("/{prefix}/{key}/injuries")
def injuries(prefix: Prefix, key: Key, session: SessionDep, settings: SettingsDep,
             request: Request) -> dict[str, Any]:
    league = LEAGUES.get(prefix)
    # No college injury report exists; an empty list would read as "everyone healthy".
    if league is None or league in COLLEGE:
        return {"supported": False, "teams": []}
    names = games.list_games_teams(session, prefix, key)
    if not names:
        raise ApiError(404, ErrorCode.NOT_FOUND, "Game not in the catalog")
    src = _espn(request, settings.sports_evidence_enabled)
    try:
        all_inj = src.injuries(league)
        teams = []
        for code, name in names.items():
            ref = src.team(league, code, name)
            items = [i for i in all_inj if ref and i["team_id"] == ref["id"]]
            teams.append({"code": code, "name": ref["name"] if ref else name, "items": items})
    except AdapterError as e:
        raise ApiError(502, ErrorCode.SOURCE_FAILURE, f"ESPN: {e}") from e
    return {"supported": True, "teams": teams}
