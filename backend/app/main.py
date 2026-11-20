"""FastAPI application factory."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware

from app import __version__
from app.api.catalog_routes import router as catalog_router
from app.api.errors import install_error_handlers
from app.api.evidence_routes import router as evidence_router
from app.api.execution_routes import router as execution_router
from app.api.games_routes import router as games_router
from app.api.history_routes import router as history_router
from app.api.investigate_routes import router as investigate_router
from app.api.jobs_routes import router as jobs_router
from app.api.ops_routes import router as ops_router
from app.api.paper_routes import router as paper_router
from app.api.research_routes import router as research_router
from app.api.routes import router
from app.api.scanner_routes import router as scanner_router
from app.api.signal_routes import router as signal_router
from app.core.clock import Clock, SystemClock
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.core.security import OriginGuardMiddleware, SecurityHeadersMiddleware
from app.db.session import make_engine, make_session_factory
from app.jobs import JobRunner


def create_app(settings: Settings | None = None, clock: Clock | None = None,
               jobs: JobRunner | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
        # Brave storage terms: drop news from investigations past the search cache window.
        try:
            from app.investigate.service import purge_expired_news

            with app.state.session_factory() as s:
                purge_expired_news(s, app.state.clock.now())
        except Exception:  # noqa: BLE001 - never block startup (e.g. table not migrated yet)
            logging.getLogger(__name__).warning("Investigation news purge skipped", exc_info=True)
        yield
        app.state.jobs.shutdown()
        if getattr(app.state, "espn", None) is not None:
            app.state.espn.close()

    app = FastAPI(
        lifespan=lifespan,
        title="Kalshi Research Terminal (local)",
        version=__version__,
        # Interactive docs are handy locally but unnecessary attack surface elsewhere.
        docs_url="/api/docs" if settings.env == "local" else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if settings.env == "local" else None,
    )
    engine = make_engine(settings.database_url)
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = make_session_factory(engine)
    app.state.clock = clock or SystemClock()
    # Mock exchange state (balance/orders) lives for the process; used only in mock env.
    from app.execution.gateway import MockExchange

    app.state.mock_exchange = MockExchange()
    # Background jobs behind the UI buttons (refresh / FRED / scan / auto-scan).
    app.state.jobs = jobs or JobRunner(settings, app.state.session_factory, app.state.clock)

    # Middleware runs outermost-last-added. Order: host check -> origin guard -> CORS.
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "X-KRT-Request"],
    )
    app.add_middleware(OriginGuardMiddleware, allowed_origins=settings.cors_origins)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)

    install_error_handlers(app)
    app.include_router(router)
    app.include_router(evidence_router)
    app.include_router(research_router)
    app.include_router(signal_router)
    app.include_router(paper_router)
    app.include_router(ops_router)
    app.include_router(execution_router)
    app.include_router(scanner_router)
    app.include_router(jobs_router)
    app.include_router(catalog_router)
    app.include_router(history_router)
    app.include_router(games_router)
    app.include_router(investigate_router)
    return app


def run() -> None:
    """Entry point that refuses non-loopback binds (validated in Settings)."""
    import uvicorn

    configure_logging()
    settings = get_settings()
    uvicorn.run(
        "app.main:create_app",
        factory=True,
        host=settings.api_host,
        port=settings.api_port,
        log_config=None,
        proxy_headers=False,
        server_header=False,
    )


if __name__ == "__main__":
    run()
