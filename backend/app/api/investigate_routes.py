"""Investigate this pick: on-demand research for one exact contract. Research only.

POST routes need the X-KRT-Request: research header (CSRF) on top of the Origin allow-list,
because later phases make them spend metered searches. GETs never compute anything costly.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Header, Path, Query, Request
from pydantic import BaseModel, Field

from app.api.errors import ApiError, ErrorCode
from app.api.routes import ClockDep, SessionDep, SettingsDep
from app.catalog import games
from app.db.models import CatalogEvent, CatalogMarket
from app.investigate import excerpts, nfl, nhl, search, service, soccer, sources, synth
from app.investigate.ledger import ledger_for
from app.investigate.schemas import Result
from app.sportsdata.espn import EspnSource
from app.sportsdata.footballdata import FootballData
from app.sportsdata.llm import LlmError, OllamaClient
from app.sportsdata.moneypuck import MoneyPuck
from app.sportsdata.news import NewsSearch
from app.sportsdata.nflverse import Nflverse
from app.sportsdata.weather import OpenMeteo

router = APIRouter(prefix="/api/research")
IdPath = Annotated[str, Path(min_length=1, max_length=36, pattern=r"^[A-Za-z0-9-]+$")]


class InvestigateIn(BaseModel):
    ticker: str = Field(min_length=3, max_length=160)
    side: str = Field(pattern=r"^(yes|no)$")
    label: str | None = Field(default=None, max_length=200)


def _csrf(h: str | None) -> None:
    if h != "research":
        raise ApiError(403, ErrorCode.VALIDATION_ERROR, "Missing X-KRT-Request header")


def _espn(request: Request, settings: Any) -> EspnSource | None:
    if not settings.sports_evidence_enabled:
        return None
    src = getattr(request.app.state, "espn", None)
    if src is None:
        src = request.app.state.espn = EspnSource(
            min_interval=settings.espn_min_request_interval_seconds
        )
    return src


def _moneypuck(request: Request, settings: Any) -> MoneyPuck | None:
    """NHL season data (MoneyPuck). None when the owner switched the source off."""
    if not sources.allows("moneypuck", "download_listed_season_csv", settings):
        return None
    src = getattr(request.app.state, "moneypuck", None)
    if src is None:
        src = MoneyPuck(settings, timeout=settings.http_timeout_seconds)
        request.app.state.moneypuck = src
    return src


def _nflverse(request: Request, settings: Any) -> Nflverse | None:
    """NFL release files (nflverse). None when the owner switched the schedule source off."""
    if not sources.allows("nflverse_schedules", "download_schedule_release", settings):
        return None
    src = getattr(request.app.state, "nflverse", None)
    if src is None:
        src = Nflverse(settings, timeout=max(settings.http_timeout_seconds, 30.0))
        request.app.state.nflverse = src
    return src


def _weather(request: Request, settings: Any) -> OpenMeteo | None:
    """Kickoff forecasts (Open-Meteo, free, no key). None when switched off."""
    if not sources.allows("open_meteo", "forecast_lookup_noncommercial", settings):
        return None
    src = getattr(request.app.state, "weather", None)
    if src is None:
        src = OpenMeteo(settings, timeout=settings.http_timeout_seconds)
        request.app.state.weather = src
    return src


def _football_data(request: Request, settings: Any) -> FootballData | None:
    """Soccer results (football-data.org, keyed). None when switched off; an adapter without
    a key is still returned so the result can say how to add one."""
    if not sources.allows("football_data_org", "read_competition_matches", settings):
        return None
    src = getattr(request.app.state, "football_data", None)
    if src is None:
        key = settings.football_data_api_key
        src = FootballData(
            settings,
            key.get_secret_value() if key is not None else None,
            timeout=settings.http_timeout_seconds,
        )
        request.app.state.football_data = src
    return src


def _model_name(settings: Any) -> str:
    return settings.ollama_model if settings.llm_provider == "ollama" else "none"


def _synthesizer(settings: Any) -> tuple[Any, OllamaClient | None]:
    """The local model's chat call (loopback Ollama only), with a tighter timeout than other
    AI features so an investigation can't hang for minutes. None when it isn't the local model."""
    if settings.llm_provider != "ollama":
        return None, None
    try:
        client = OllamaClient(
            settings.ollama_base_url,
            settings.ollama_model,
            num_ctx=settings.ollama_num_ctx,
            timeout=min(settings.llm_timeout_seconds, synth.SYNTH_TIMEOUT),
        )
    except LlmError:
        return None, None
    return client.chat_json, client


def _gatherer(request: Request, settings: Any, now: Any) -> Any:
    """News discovery for an explicit run. Built only inside POST handlers, so nothing else
    (GET, preflight, page load, expanding the full view) can spend a search."""
    key = settings.brave_search_api_key
    cache = request.app.state.__dict__.setdefault("research_search_cache", {})

    def client(on_attempt: Any) -> NewsSearch:
        # max_retries=0: every attempt is billed, so a failure isn't retried automatically.
        return NewsSearch(
            key.get_secret_value(),
            timeout=settings.http_timeout_seconds,
            max_retries=0,
            on_attempt=on_attempt,
        )

    def run(h: Any, teams: list[dict[str, Any]]) -> search.Gathered:
        return search.gather(
            h,
            teams,
            configured=key is not None,
            client_factory=client,
            ledger=ledger_for(request.app.state),
            cache=cache,
            cache_ttl=timedelta(hours=settings.research_search_cache_hours),
            now=now,
            max_searches=settings.research_max_searches_per_investigation,
            max_sources=settings.research_max_sources_per_investigation,
        )

    return run


def _run(
    session: Any,
    settings: Any,
    request: Request,
    now: Any,
    ticker: str,
    side: str,
    label: str | None,
    refresh: bool,
) -> Result:
    if not games.TICKER_RE.match(ticker):
        raise ApiError(422, ErrorCode.VALIDATION_ERROR, "Bad ticker")
    service.purge_expired_news(session, now)
    m = session.get(CatalogMarket, ticker)
    if m is None:
        raise ApiError(404, ErrorCode.NOT_FOUND, f"{ticker} is not in the catalog (run a scan)")
    key = service.cache_key(ticker, side, m, _model_name(settings))
    if not refresh:
        hit = service.cached(session, key, now)
        if hit is not None:
            return hit
    synth_chat, client = _synthesizer(settings)
    try:
        r = service.build(
            session,
            _espn(request, settings),
            ticker,
            side,
            label,
            now,
            settings.research_search_cache_hours,
            gatherer=_gatherer(request, settings, now),
            synthesizer=synth_chat,
            mp_src=_moneypuck(request, settings) if nhl.is_nhl(ticker) else None,
            nv_src=_nflverse(request, settings) if nfl.is_nfl(ticker) else None,
            wx_src=_weather(request, settings) if nfl.is_nfl(ticker) else None,
            fd_src=_football_data(request, settings) if soccer.is_soccer(ticker) else None,
        )
    except service.Unsupported as e:
        raise ApiError(422, ErrorCode.VALIDATION_ERROR, str(e)) from e
    except service.NotFound as e:
        raise ApiError(404, ErrorCode.NOT_FOUND, str(e)) from e
    finally:
        if client is not None:
            client.close()
    service.save(session, key, r)
    return r


@router.post("/investigations", response_model=Result)
def start(
    body: InvestigateIn,
    session: SessionDep,
    settings: SettingsDep,
    clock: ClockDep,
    request: Request,
    x_krt_request: Annotated[str | None, Header(alias="X-KRT-Request")] = None,
) -> Result:
    _csrf(x_krt_request)
    return _run(
        session, settings, request, clock.now(), body.ticker, body.side, body.label, refresh=False
    )


@router.get("/investigations/{inv_id}", response_model=Result)
def get_one(inv_id: IdPath, session: SessionDep, clock: ClockDep) -> Result:
    service.purge_expired_news(session, clock.now())
    r = service.load(session, inv_id)
    if r is None:
        raise ApiError(404, ErrorCode.NOT_FOUND, "Investigation not found")
    return r


@router.post("/investigations/{inv_id}/refresh", response_model=Result)
def refresh(
    inv_id: IdPath,
    session: SessionDep,
    settings: SettingsDep,
    clock: ClockDep,
    request: Request,
    x_krt_request: Annotated[str | None, Header(alias="X-KRT-Request")] = None,
) -> Result:
    _csrf(x_krt_request)
    old = service.load(session, inv_id)
    if old is None:
        raise ApiError(404, ErrorCode.NOT_FOUND, "Investigation not found")
    h = old.hypothesis
    new = _run(session, settings, request, clock.now(), h.ticker, h.side, h.label, refresh=True)
    if not excerpts.excerpts_of(old):
        return new
    # The user's excerpts are their own notes: keep them across a refresh (no search spent).
    chat, client = _synthesizer(settings)
    try:
        new = excerpts.carry(old, new, chat)
    finally:
        if client is not None:
            client.close()
    service.update(session, new)
    return new


def _edit(session: Any, settings: Any, clock: Any, inv_id: str, change: Any) -> Result:
    """Apply an excerpt change to a stored investigation. Free: no search, no data request;
    only the local model when it's the configured provider."""
    service.purge_expired_news(session, clock.now())
    r = service.load(session, inv_id)
    if r is None:
        raise ApiError(404, ErrorCode.NOT_FOUND, "Investigation not found")
    chat, client = _synthesizer(settings)
    try:
        out = change(r, chat)
    except excerpts.Unsupported as e:
        raise ApiError(422, ErrorCode.VALIDATION_ERROR, str(e)) from e
    except KeyError as e:
        raise ApiError(404, ErrorCode.NOT_FOUND, "Excerpt not found") from e
    finally:
        if client is not None:
            client.close()
    service.update(session, out)
    return out


@router.post("/investigations/{inv_id}/excerpts", response_model=Result)
def add_excerpt(
    inv_id: IdPath,
    body: excerpts.ExcerptIn,
    session: SessionDep,
    settings: SettingsDep,
    clock: ClockDep,
    x_krt_request: Annotated[str | None, Header(alias="X-KRT-Request")] = None,
) -> Result:
    """Add text the user pasted. The link is stored for the user, never fetched."""
    _csrf(x_krt_request)
    if "user_excerpt" in sources.disabled(settings):
        raise ApiError(
            403,
            ErrorCode.VALIDATION_ERROR,
            "Excerpts are switched off (KRT_RESEARCH_DISABLED_SOURCES).",
        )
    return _edit(
        session, settings, clock, inv_id, lambda r, chat: excerpts.add(r, body, clock.now(), chat)
    )


@router.post("/investigations/{inv_id}/excerpts/{excerpt_id}/remove", response_model=Result)
def remove_excerpt(
    inv_id: IdPath,
    excerpt_id: Annotated[str, Path(pattern=r"^U[0-9]{1,2}$")],
    session: SessionDep,
    settings: SettingsDep,
    clock: ClockDep,
    x_krt_request: Annotated[str | None, Header(alias="X-KRT-Request")] = None,
) -> Result:
    _csrf(x_krt_request)
    return _edit(
        session, settings, clock, inv_id, lambda r, chat: excerpts.remove(r, excerpt_id, chat)
    )


@router.get("/usage")
def usage(settings: SettingsDep, request: Request) -> dict[str, Any]:
    """Brave requests sent by the WHOLE app (what the caps apply to), with a per-feature
    breakdown, from this app's own ledger. Not your Brave balance or bill: the API doesn't
    expose those, so no "$ remaining" is ever shown."""
    used = ledger_for(request.app.state).usage()
    return {
        "configured": settings.brave_search_api_key is not None,
        "used_today": used["total_today"],
        "daily_cap": settings.research_brave_daily_request_cap,
        "used_month": used["total_month"],
        "monthly_cap": settings.research_brave_monthly_request_cap,
        "by_purpose": used["by_purpose"],
        "max_searches_per_investigation": settings.research_max_searches_per_investigation,
    }


@router.get("/sources")
def source_rights(settings: SettingsDep) -> dict[str, Any]:
    """The data-source rights matrix (reviewed terms, allowed operations, owner switches).
    Read-only: rights can't be granted through the API."""
    return {"version": sources.SOURCES_VERSION, "sources": sources.matrix(settings)}


@router.get("/preflight")
def preflight(
    session: SessionDep,
    settings: SettingsDep,
    clock: ClockDep,
    request: Request,
    ticker: Annotated[str, Query(min_length=3, max_length=160)],
    side: Annotated[str, Query(pattern=r"^(yes|no)$")],
) -> dict[str, Any]:
    """Before running: quote, whether a cached result exists, and budget. Free (no ESPN call,
    no search, no model)."""
    if not games.TICKER_RE.match(ticker):
        raise ApiError(422, ErrorCode.VALIDATION_ERROR, "Bad ticker")
    m = session.get(CatalogMarket, ticker)
    if m is None:
        raise ApiError(404, ErrorCode.NOT_FOUND, f"{ticker} is not in the catalog (run a scan)")
    e = session.get(CatalogEvent, m.event_ticker)
    series = e.series_ticker if e else ticker.split("-")[0]
    now = clock.now()
    try:
        service.check_supported(ticker, m.event_ticker, series)
        unsupported = None
    except service.Unsupported as exc:
        unsupported = str(exc)
    return {
        "quote": service.quote_for(m, side, now).model_dump(),
        "model": None
        if unsupported is not None
        else "No NHL model: MoneyPuck season data for context (checked when you run it)"
        if nhl.is_nhl(ticker)
        else "No NFL model: nflverse season data and kickoff weather for context (checked "
        "when you run it)"
        if nfl.is_nfl(ticker)
        else "No soccer model: football-data.org results for context (checked when you run "
        "it; needs KRT_FOOTBALL_DATA_API_KEY)"
        if soccer.is_soccer(ticker)
        else "Box-score history (frequency, checked when you run it)",
        "cached": service.cached(
            session, service.cache_key(ticker, side, m, _model_name(settings)), now
        )
        is not None,
        "unsupported": unsupported,
        "usage": usage(settings, request),
    }
