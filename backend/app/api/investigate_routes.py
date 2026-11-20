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
from app.investigate import search, service, synth
from app.investigate.ledger import ledger_for
from app.investigate.schemas import Result
from app.sportsdata.espn import EspnSource
from app.sportsdata.llm import LlmError, OllamaClient
from app.sportsdata.news import NewsSearch

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
    return _run(session, settings, request, clock.now(), h.ticker, h.side, h.label, refresh=True)


@router.get("/usage")
def usage(settings: SettingsDep, request: Request) -> dict[str, Any]:
    """Research searches sent, from this app's own ledger, against this app's caps.
    Not your Brave balance or bill: the API doesn't expose those."""
    used = ledger_for(request.app.state).usage("research")
    return {
        "configured": settings.brave_search_api_key is not None,
        "used_today": used["used_today"],
        "daily_cap": settings.research_brave_daily_request_cap,
        "used_month": used["used_month"],
        "monthly_cap": settings.research_brave_monthly_request_cap,
        "max_searches_per_investigation": settings.research_max_searches_per_investigation,
    }


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
        "model": "Box-score history (frequency, checked when you run it)"
        if unsupported is None
        else None,
        "cached": service.cached(
            session, service.cache_key(ticker, side, m, _model_name(settings)), now
        )
        is not None,
        "unsupported": unsupported,
        "usage": usage(settings, request),
    }
