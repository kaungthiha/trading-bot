"""FastAPI application factory."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware

from app import __version__
from app.api.errors import install_error_handlers
from app.api.evidence_routes import router as evidence_router
from app.api.research_routes import router as research_router
from app.api.routes import router
from app.api.signal_routes import router as signal_router
from app.core.clock import Clock, SystemClock
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.core.security import OriginGuardMiddleware, SecurityHeadersMiddleware
from app.db.session import make_engine, make_session_factory


def create_app(settings: Settings | None = None, clock: Clock | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(
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

    # Middleware runs outermost-last-added. Order: host check -> origin guard -> CORS.
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )
    app.add_middleware(OriginGuardMiddleware, allowed_origins=settings.cors_origins)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)

    install_error_handlers(app)
    app.include_router(router)
    app.include_router(evidence_router)
    app.include_router(research_router)
    app.include_router(signal_router)
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
