"""My trades: your synced Kalshi history, P&L, behavior and suggestions. Read-only GETs;
syncing runs as the 'history' job (POST /api/jobs/history/run, ops CSRF header)."""

from __future__ import annotations

import logging
import re
from datetime import timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Header, Query, Request
from pydantic import BaseModel
from pydantic import Field as PydField

from app.api.errors import ApiError, ErrorCode
from app.api.routes import ClockDep, SessionDep, SettingsDep
from app.history.analysis import fills_page, report
from app.history.positions import open_analysis
from app.history.similar import similar
from app.investigate.ledger import record_hook
from app.sportsdata.espn import EspnSource
from app.sportsdata.evidence import avg_text
from app.sportsdata.llm import LlmError, llm_status, local_reviewer
from app.sportsdata.news import headlines

router = APIRouter(prefix="/api/history")
log = logging.getLogger(__name__)


@router.get("/status")
def history_status(settings: SettingsDep) -> dict[str, Any]:
    return {"configured": settings.kalshi_api_key_id is not None
            and settings.kalshi_private_key_path is not None,
            "kalshi_env": settings.kalshi_env.value}


@router.get("/report")
def history_report(session: SessionDep, settings: SettingsDep) -> dict[str, Any]:
    return report(session, settings.experiment_budget_dollars)


def _espn(settings: Any, request: Request) -> EspnSource | None:
    if not settings.sports_evidence_enabled:
        return None
    src = getattr(request.app.state, "espn", None)
    if src is None:
        src = request.app.state.espn = EspnSource(
            min_interval=settings.espn_min_request_interval_seconds)
    return src


@router.get("/open")
def history_open(session: SessionDep, settings: SettingsDep, clock: ClockDep,
                 request: Request) -> dict[str, Any]:
    """Open positions with today's prices, box-score evidence (ESPN) and flags."""
    return open_analysis(session, _espn(settings, request), settings.experiment_budget_dollars,
                         clock.now())


# --- Coach (local AI) ---------------------------------------------------------------------------

COACH_TTL = timedelta(minutes=30)


@router.get("/coach/status")
def coach_status(settings: SettingsDep) -> dict[str, Any]:
    return llm_status(settings)


def coach_facts(rep: dict[str, Any], opened: dict[str, Any]) -> dict[str, Any]:
    """The record, compacted for a small model's context window."""
    pos = []
    for p in opened["positions"][:20]:
        ev = p.get("evidence") or {}
        pos.append({"ticker": p["ticker"], "market": p["title"], "side": p["side"],
                    "paid": p["avg_cost"], "now": p["mid"], "cost": p["cost"],
                    "unrealized": p["unrealized"], "hours_left": p["hours_to_close"],
                    "box_score_verdict": ev.get("verdict"),
                    "combo_legs": None if not p.get("combo") else {
                        k: p["combo"][k] for k in ("won", "lost", "open")},
                    "flags": [f["text"] for f in p["flags"]]})
    return {
        "summary": rep["summary"], "behavior": rep["behavior"],
        "entry_quality": rep.get("entry_quality"), "combos": rep.get("combo_breakdown"),
        "by_market_type": rep["by_type"], "won_vs_price_paid": rep["calibration"],
        "rule_based_playbook": rep.get("playbook"),
        "observations": [i["text"] for i in rep["insights"]],
        "open_portfolio": opened["portfolio"], "open_positions": pos,
    }


@router.post("/coach")
def coach(session: SessionDep, settings: SettingsDep, clock: ClockDep, request: Request,
          x_krt_request: Annotated[str | None, Header(alias="X-KRT-Request")] = None
          ) -> dict[str, Any]:
    if x_krt_request != "review":
        raise ApiError(403, ErrorCode.VALIDATION_ERROR, "Missing X-KRT-Request header")
    rep = report(session, settings.experiment_budget_dollars)
    sync_at = (rep.get("last_sync") or {}).get("at")
    now = clock.now()
    cache = getattr(request.app.state, "coach_cache", None)
    if cache and cache["sync"] == sync_at and now - cache["at"] < COACH_TTL:
        return {**cache["out"], "cached": True}
    try:
        reviewer = local_reviewer(settings)
    except LlmError as e:
        raise ApiError(409, ErrorCode.SOURCE_FAILURE, str(e)) from e
    opened = open_analysis(session, _espn(settings, request), settings.experiment_budget_dollars,
                           now)
    try:
        out = reviewer.coach(coach_facts(rep, opened), {p["ticker"] for p in opened["positions"]})
    except LlmError as e:
        raise ApiError(502, ErrorCode.SOURCE_FAILURE, str(e)) from e
    finally:
        reviewer.close()
    out["generated_at"] = now.isoformat()
    request.app.state.coach_cache = {"sync": sync_at, "at": now, "out": out}
    return {**out, "cached": False}


# --- Open positions read (local AI) -------------------------------------------------------------

OPEN_TTL = timedelta(minutes=15)


def open_facts(opened: dict[str, Any], heads: list[dict[str, str]], budget: Any
               ) -> tuple[dict[str, Any], dict[str, str]]:
    """Each open position as compact facts with an id (P1...) the model refers to."""
    ids: dict[str, str] = {}
    pos = []
    for i, p in enumerate(opened["positions"][:15], 1):
        pid = f"P{i}"
        ids[pid] = p["ticker"]
        ev = p.get("evidence") or {}
        trail = p.get("trail") or []
        f: dict[str, Any] = {
            "id": pid, "market": p["title"], "event": p.get("event_title"), "type": p["type"],
            "side": p["side"], "contracts": p["contracts"], "paid": p["avg_cost"],
            "now": p["mid"], "cost": p["cost"], "unrealized": p["unrealized"],
            "max_payout": p["max_payout"], "hours_to_close": p["hours_to_close"],
            "price_trail": [round(float(t["mid"]), 3) for t in trail[-8:]
                            if t.get("mid") is not None],
            "flags": [x["text"] for x in p["flags"]]}
        if ev:
            f["history"] = {k: ev.get(k) for k in ("windows", "estimate", "interval",
                                                   "verdict", "line")}
            f["history"]["season_average"] = avg_text(ev)
            if ev.get("injury"):
                f["injury"] = f"{ev['injury']['status']}: {ev['injury']['detail']}"[:200]
        elif p.get("evidence_note"):
            f["history"] = f"none ({p['evidence_note']})"
        if p.get("combo"):
            c = p["combo"]
            f["combo"] = {"fair_now": c.get("fair"), "won": c["won"], "lost": c["lost"],
                          "open": c["open"],
                          "legs": [{"leg": f"{lg['side'].upper()} {lg['title']}",
                                    "status": lg["status"], "now": lg.get("probability")}
                                   for lg in c["legs"][:12]]}
        pos.append(f)
    facts = {"budget": None if budget is None else str(budget),
             "portfolio": opened["portfolio"], "same_game_groups": opened.get("correlation"),
             "positions": pos,
             "headlines": [{k: h[k] for k in ("id", "about", "title", "source", "age",
                                               "snippet")} for h in heads]}
    return facts, ids


_PID = re.compile(r"\bP(\d{1,2})\b")


def short_name(p: dict[str, Any]) -> str:
    t = str(p.get("title") or p["ticker"]).removeprefix("Will ").rstrip("?")
    return t if len(t) <= 36 else t[:34].rstrip() + "…"


def named(text: str, names: dict[str, str]) -> str:
    """'P3 and P4' -> '"Best AI on Dec 31, 2026" and ...' (unknown ids are left as is)."""
    return _PID.sub(lambda m: f"“{names[m.group(0)]}”" if m.group(0) in names
                    else m.group(0), text)


@router.post("/open/review")
def open_review(session: SessionDep, settings: SettingsDep, clock: ClockDep, request: Request,
                x_krt_request: Annotated[str | None, Header(alias="X-KRT-Request")] = None
                ) -> dict[str, Any]:
    if x_krt_request != "review":
        raise ApiError(403, ErrorCode.VALIDATION_ERROR, "Missing X-KRT-Request header")
    now = clock.now()
    opened = open_analysis(session, _espn(settings, request), settings.experiment_budget_dollars,
                           now)
    if not opened["positions"]:
        raise ApiError(409, ErrorCode.VALIDATION_ERROR, "No open positions to review")
    ck = tuple((p["ticker"], p["contracts"]) for p in opened["positions"])
    cache = getattr(request.app.state, "open_review_cache", None)
    if cache and cache["key"] == ck and now - cache["at"] < OPEN_TTL:
        return {**cache["out"], "cached": True}
    try:
        reviewer = local_reviewer(settings)
    except LlmError as e:
        raise ApiError(409, ErrorCode.SOURCE_FAILURE, str(e)) from e
    subjects = list(dict.fromkeys(
        (p.get("evidence") or {}).get("subject", {}).get("name")
        for p in opened["positions"] if (p.get("evidence") or {}).get("subject")))
    heads = headlines(settings, subjects, prefix="H", per=2, limit=5,
                      on_attempt=record_hook(request.app.state, "headlines"))
    facts, ids = open_facts(opened, heads, settings.experiment_budget_dollars)
    try:
        out = reviewer.open_review(facts, ids, {h["id"] for h in heads})
    except LlmError as e:
        raise ApiError(502, ErrorCode.SOURCE_FAILURE, str(e)) from e
    finally:
        reviewer.close()
    # The model refers to positions as P1, P2...; the page shows market names.
    names = {pid: short_name(p) for pid, p in zip(ids, opened["positions"], strict=False)}
    out["summary"] = named(out["summary"], names)
    out["portfolio"] = [named(x, names) for x in out["portfolio"]]
    out["check"] = [named(x, names) for x in out["check"]]
    for r in out["positions"]:
        r["read"], r["plan"] = named(r["read"], names), named(r["plan"], names)
    out["sources"] = [{k: h[k] for k in ("id", "title", "source", "age", "url")} for h in heads]
    out["generated_at"] = now.isoformat()
    request.app.state.open_review_cache = {"key": ck, "at": now, "out": out}
    return {**out, "cached": False}


_TICKER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,159}$")


@router.get("/similar")
def history_similar(session: SessionDep, settings: SettingsDep,
                    legs: Annotated[str, Query(max_length=2000)] = "",
                    series: Annotated[str, Query(max_length=1000)] = "") -> dict[str, Any]:
    """How trades like these went for you (Docket, research pages). Read-only, local data.
    legs = "TICKER:side,..." ; series = "SERIES,...". Groups under the sample threshold
    carry counts only (see app.history.similar)."""
    tickers = [p.split(":", 1)[0] for p in legs.split(",") if p][:12]
    extra = [x for x in series.split(",") if x][:6]
    if any(not _TICKER.match(t) for t in tickers + extra):
        raise ApiError(422, ErrorCode.VALIDATION_ERROR, "Bad ticker")
    rep = report(session, settings.experiment_budget_dollars)
    rows = rep["markets"]
    titles = {r["series"]: r["series_title"] for r in rows}
    out = similar(rows, tickers, extra, (rep.get("combo_breakdown") or {}).get("by_size"), titles)
    out["synced_at"] = (rep.get("last_sync") or {}).get("at")
    return out


@router.get("/fills")
def history_fills(session: SessionDep,
                  limit: Annotated[int, Query(ge=1, le=500)] = 100,
                  offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0) -> dict[str, Any]:
    return {"items": fills_page(session, limit, offset), "limit": limit, "offset": offset}


# --- Daily review, leg record, lessons, warnings ------------------------------------------------

_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DAY_REVIEW_TTL = timedelta(minutes=30)
RECAP_SEARCHES = 8


def _day_arg(day: str) -> str:
    if not _DAY.match(day):
        raise ApiError(422, ErrorCode.VALIDATION_ERROR, "date must be YYYY-MM-DD")
    return day


def _fill_day_outcomes(request: Request, settings: Any, clock: Any, day: str,
                       max_subjects: int) -> dict[str, int] | None:
    """Look up what the players on this day's legs actually did (ESPN; cached in the DB)."""
    from app.history.daily import et_day
    from app.history.journal import _buys
    from app.history.legs import leg_rows
    from app.history.postmortem import fill_outcomes

    src = _espn(settings, request)
    if src is None:
        return None
    factory = request.app.state.session_factory
    with factory() as s:
        combos = {t for t, b in _buys(s).items() if et_day(b["first_at"]) == day}
        rows = leg_rows(s, combos)
    try:
        return fill_outcomes(factory, src, rows, clock.now(), max_subjects=max_subjects)
    except Exception:  # noqa: BLE001 - box scores are context; the day still shows
        log.warning("box-score lookups failed", exc_info=True)
        return None


@router.get("/days")
def history_days(session: SessionDep, settings: SettingsDep) -> dict[str, Any]:
    from app.history.daily import days

    rep = report(session, settings.experiment_budget_dollars)
    return {"days": days(session, rep)}


@router.get("/day")
def history_day(session: SessionDep, settings: SettingsDep, clock: ClockDep, request: Request,
                date: Annotated[str, Query(max_length=10)]) -> dict[str, Any]:
    """One day's bets with every leg, what the players actually did, and the legs that sank
    you. Box scores are looked up on first view (a bounded number of players per load)."""
    from app.history.daily import day_detail

    day = _day_arg(date)
    checked = _fill_day_outcomes(request, settings, clock, day, max_subjects=12)
    rep = report(session, settings.experiment_budget_dollars)
    out = day_detail(session, rep, day)
    out["box_scores"] = checked
    return out


class DayIn(BaseModel):
    date: str = PydField(min_length=10, max_length=10)


def _recap_news(state: Any, settings: Any, request: Request, detail: dict[str, Any]
                ) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """Recap news for the legs that sank you: up to RECAP_SEARCHES Brave searches (app-wide
    cap, tag "review"), cached per query with the slate's news."""
    from app.history.review_ai import recap_queries
    from app.investigate.ledger import BudgetExhausted, ledger_for
    from app.sportsdata.espn import LEAGUES
    from app.sportsdata.news import NewsSearch
    from app.sportsdata.slate import NewsCache

    key = settings.brave_search_api_key
    info: dict[str, Any] = {"searched": 0, "items": 0, "status": "off"}
    news: list[dict[str, str]] = []
    if key is None:
        info["status"] = "no_key"
        return news, info
    if not detail["breakers"]:
        return news, info
    src = _espn(settings, request)
    names: dict[str, str] = {}
    if src is not None:
        for x in detail["breakers"][:RECAP_SEARCHES]:
            league = LEAGUES.get(x.get("prefix") or "")
            for code in x.get("teams") or []:
                if league and code not in names:
                    try:
                        ref = src.team(league, code)
                    except Exception:  # noqa: BLE001 - names are a nicety
                        ref = None
                    names[code] = ref["name"] if ref else code
    current = {"q": ""}
    client = NewsSearch(key.get_secret_value(), timeout=settings.http_timeout_seconds,
                        on_attempt=ledger_for(state).attempt_hook("review",
                                                                  lambda: current["q"]))
    if getattr(state, "slate_news", None) is None:
        state.slate_news = NewsCache(settings.research_search_cache_hours, state.clock.now)
    info["status"] = "ok"

    def fetch(q: str) -> list[dict[str, str]]:
        current["q"] = q
        info["searched"] += 1
        return [{"title": it["title"], "source": it["source"], "age": it["age"],
                 "snippet": it["description"], "url": it["url"]}
                for it in client.search(q, count=3)]
    try:
        for about, q in recap_queries(detail, names, RECAP_SEARCHES):
            try:
                items = state.slate_news.get(q, fetch)
            except BudgetExhausted as e:
                info["status"], info["message"] = "budget", str(e)
                break
            except Exception:  # noqa: BLE001 - one failed search never sinks the review
                log.info("recap search failed", exc_info=True)
                continue
            for it in items:
                news.append({"id": f"N{len(news) + 1}", "about": about, **it})
    finally:
        client.close()
    info["items"] = len(news)
    return news, info


@router.post("/day/review")
def history_day_review(body: DayIn, session: SessionDep, settings: SettingsDep, clock: ClockDep,
                       request: Request,
                       x_krt_request: Annotated[str | None, Header(alias="X-KRT-Request")] = None
                       ) -> dict[str, Any]:
    """The local model reviews one day: what went right and wrong, and lessons it saves for
    next time (they flag future bets that repeat them)."""
    if x_krt_request != "review":
        raise ApiError(403, ErrorCode.VALIDATION_ERROR, "Missing X-KRT-Request header")
    from app.history.daily import day_detail
    from app.history.legs import active_lessons, leg_record
    from app.history.review_ai import day_facts, review_day, save_lessons
    from app.sportsdata.llm import make_client

    day = _day_arg(body.date)
    now = clock.now()
    state = request.app.state
    cache = getattr(state, "day_review_cache", None) or {}
    hit = cache.get(day)
    if hit and now - hit["at"] < DAY_REVIEW_TTL:
        return {**hit["out"], "cached": True}
    if settings.llm_provider != "ollama":
        raise ApiError(409, ErrorCode.SOURCE_FAILURE,
                       "The day review runs on the local model only (KRT_LLM_PROVIDER=ollama)")
    _fill_day_outcomes(request, settings, clock, day, max_subjects=30)
    rep = report(session, settings.experiment_budget_dollars)
    detail = day_detail(session, rep, day)
    if not detail["bets"]:
        raise ApiError(409, ErrorCode.VALIDATION_ERROR, "No bets on that day")
    news, info = _recap_news(state, settings, request, detail)
    facts = day_facts(detail, leg_record(session), news, active_lessons(session))
    subjects = {lg["subject"] for b in detail["bets"] for lg in b["legs"]}
    llm = make_client(settings)
    try:
        out = review_day(llm, facts, subjects, {n["id"] for n in news})
    except LlmError as e:
        raise ApiError(502, ErrorCode.SOURCE_FAILURE, str(e)) from e
    finally:
        llm.close()
    saved = save_lessons(session, day, out["lessons"], now)
    out.update({"date": day, "generated_at": now.isoformat(), "news_info": info,
                "news": [{k: n[k] for k in ("id", "about", "title", "source", "age", "url")}
                         for n in news],
                "lessons_saved": len(saved)})
    cache[day] = {"at": now, "out": out}
    state.day_review_cache = cache
    return {**out, "cached": False}


@router.get("/top")
def history_top(session: SessionDep, settings: SettingsDep) -> dict[str, Any]:
    from app.history.daily import top_bets

    return top_bets(session, report(session, settings.experiment_budget_dollars))


@router.get("/legs")
def history_legs(session: SessionDep) -> dict[str, Any]:
    from app.history.legs import leg_record

    return leg_record(session)


@router.get("/warnings")
def history_warnings(session: SessionDep,
                     legs: Annotated[str, Query(max_length=2000)] = "") -> dict[str, Any]:
    """Past mistakes that a new bet repeats. legs = "TICKER:side,..." (local data only)."""
    from app.history.legs import warnings_for

    parsed = []
    for p in [x for x in legs.split(",") if x][:12]:
        t, _, side = p.partition(":")
        if not _TICKER.match(t) or side not in ("yes", "no"):
            raise ApiError(422, ErrorCode.VALIDATION_ERROR, "Bad leg")
        parsed.append({"ticker": t, "side": side})
    return warnings_for(session, parsed)


@router.get("/lessons")
def lessons_list(session: SessionDep) -> dict[str, Any]:
    from sqlalchemy import select

    from app.db.models import Lesson

    rows = session.scalars(select(Lesson).where(Lesson.active.is_(True))
                           .order_by(Lesson.created_at.desc()).limit(100))
    return {"items": [{"id": x.id, "day": x.day, "text": x.text, "player": x.player,
                       "stat": x.stat, "side": x.side, "author": x.author,
                       "created_at": x.created_at.isoformat()} for x in rows]}


class LessonIn(BaseModel):
    text: str = PydField(min_length=3, max_length=240)
    player: str | None = PydField(default=None, max_length=120)
    stat: str | None = PydField(default=None, max_length=12)
    side: str | None = PydField(default=None, pattern="^(yes|no)$")
    day: str | None = PydField(default=None, max_length=10)


def _lesson_header(x: str | None) -> None:
    if x != "lesson":
        raise ApiError(403, ErrorCode.VALIDATION_ERROR, "Missing X-KRT-Request header")


@router.post("/lessons")
def lessons_add(body: LessonIn, session: SessionDep, clock: ClockDep,
                x_krt_request: Annotated[str | None, Header(alias="X-KRT-Request")] = None
                ) -> dict[str, Any]:
    from app.history.daily import et_day
    from app.history.legs import LESSON_CODES
    from app.history.review_ai import save_lessons

    _lesson_header(x_krt_request)
    now = clock.now()
    stat = (body.stat or "").upper() or None
    if stat is not None and stat not in LESSON_CODES:
        raise ApiError(422, ErrorCode.VALIDATION_ERROR, "Unknown stat")
    day = _day_arg(body.day) if body.day else et_day(now)
    player = (body.player or "").strip() or None
    saved = save_lessons(session, day, [{"text": body.text.strip(), "player": player,
                                         "stat": stat,
                                         "side": body.side if (player or stat) else None}], now,
                         author="you")
    return {"saved": len(saved)}


@router.post("/lessons/{lesson_id}/remove")
def lessons_remove(lesson_id: int, session: SessionDep,
                   x_krt_request: Annotated[str | None, Header(alias="X-KRT-Request")] = None
                   ) -> dict[str, Any]:
    from app.db.models import Lesson

    _lesson_header(x_krt_request)
    row = session.get(Lesson, lesson_id)
    if row is None:
        raise ApiError(404, ErrorCode.NOT_FOUND, "No such lesson")
    row.active = False
    session.commit()
    return {"removed": lesson_id}
