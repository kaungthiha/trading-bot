"""My trades: your synced Kalshi history, P&L, behavior and suggestions. Read-only GETs;
syncing runs as the 'history' job (POST /api/jobs/history/run, ops CSRF header)."""

from __future__ import annotations

import re
from datetime import timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Header, Query, Request

from app.api.errors import ApiError, ErrorCode
from app.api.routes import ClockDep, SessionDep, SettingsDep
from app.history.analysis import fills_page, report
from app.history.positions import open_analysis
from app.history.similar import similar
from app.sportsdata.espn import EspnSource
from app.sportsdata.evidence import avg_text
from app.sportsdata.llm import LlmError, llm_status, local_reviewer
from app.sportsdata.news import headlines

router = APIRouter(prefix="/api/history")


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
    heads = headlines(settings, subjects, prefix="H", per=2, limit=5)
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
