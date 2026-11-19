"""Build the configured gateway. Mock state (balance, orders) lives for the process."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import ExecutionEnv, Settings
from app.db.models import Market, QuoteSnapshot
from app.execution.gateway import ExecutionGateway, KalshiDemoGateway, MockExchange
from app.execution.service import ExecutionError, _local_book
from app.execution.signing import Signer
from app.signals.mapping import current_rules


def sync_mock_from_db(mock: MockExchange, s: Session) -> MockExchange:
    """Mirror local markets/rules/latest books into the mock (balance/orders preserved)."""
    for m in s.scalars(select(Market)).all():
        rules = current_rules(s, m.id)
        q = s.scalar(select(QuoteSnapshot).where(QuoteSnapshot.market_id == m.id)
                     .order_by(QuoteSnapshot.observed_at.desc()).limit(1))
        mock.markets[m.external_ticker] = {
            "ticker": m.external_ticker, "status": m.status,
            "rules_primary": rules.rules_text if rules else "", "rules_secondary": None,
        }
        if q is not None:
            mock.books[m.external_ticker] = {"orderbook_fp": _local_book(q.depth_json)}
    return mock


def build_gateway(settings: Settings, s: Session, mock: MockExchange | None) -> ExecutionGateway:
    if settings.execution_env is ExecutionEnv.MOCK:
        return sync_mock_from_db(mock or MockExchange(), s)
    if settings.kalshi_demo_api_key_id is None or settings.kalshi_demo_private_key_path is None:
        raise ExecutionError("DEMO_CREDENTIALS_MISSING",
                             "Set KRT_KALSHI_DEMO_API_KEY_ID and KRT_KALSHI_DEMO_PRIVATE_KEY_PATH")
    path = settings.kalshi_demo_private_key_path
    if not path.is_file():
        raise ExecutionError("DEMO_KEY_FILE_MISSING")
    signer = Signer.from_pem_file(settings.kalshi_demo_api_key_id.get_secret_value(), path)
    return KalshiDemoGateway(signer, timeout=settings.http_timeout_seconds)
