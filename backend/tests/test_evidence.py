"""Evidence pipeline tests. FRED payloads below are SYNTHETIC, shaped like the documented
series / series/observations JSON responses (docs checked 2026-11-18)."""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.adapters.base import AdapterError, AdapterErrorCode
from app.core.clock import FrozenClock
from app.core.config import Settings
from app.db.models import EvidenceRecord, IngestionRun
from app.db.session import make_engine, make_session_factory
from app.evidence.fred import FredClient, FredEvidenceAdapter, parse_value
from app.evidence.ingest import run_evidence_ingestion
from app.evidence.models import EvidenceQuality
from app.evidence.repository import EvidenceRepository, is_fresh
from app.evidence.sources import FRED_NOTICE, SOURCES
from app.main import create_app

KEY = "0123456789abcdef0123456789abcdef"  # fake, correctly shaped
SPEC = SOURCES["fred:CPIAUCSL"]
NOW = datetime(2026, 11, 18, 15, 0, tzinfo=UTC)

SERIES = {
    "realtime_start": "2026-11-18",
    "realtime_end": "2026-11-18",
    "seriess": [
        {
            "id": "CPIAUCSL",
            "title": "Consumer Price Index for All Urban Consumers: All Items",
            "frequency": "Monthly",
            "units": "Index 1982-1984=100",
            "seasonal_adjustment": "Seasonally Adjusted",
            "last_updated": "2026-11-10 07:41:02-06",
            "notes": "Synthetic notes.",
        }
    ],
}

ROWS = [
    # Aug 2026 first published Sep 11, then revised Oct 15
    {"realtime_start": "2026-09-11", "realtime_end": "2026-10-14", "date": "2026-08-01",
     "value": "320.0"},
    {"realtime_start": "2026-10-15", "realtime_end": "9999-12-31", "date": "2026-08-01",
     "value": "320.4"},
    {"realtime_start": "2026-10-15", "realtime_end": "9999-12-31", "date": "2026-09-01",
     "value": "321.1"},
    {"realtime_start": "2026-11-10", "realtime_end": "9999-12-31", "date": "2026-10-01",
     "value": "."},
]


def observations_body(rows: list[dict], offset: int = 0, count: int | None = None) -> dict:
    return {
        "realtime_start": "1776-07-04",
        "realtime_end": "9999-12-31",
        "output_type": 1,
        "file_type": "json",
        "count": len(rows) if count is None else count,
        "offset": offset,
        "limit": 100000,
        "observations": rows,
    }


class Rec:
    def __init__(self, handler):  # type: ignore[no-untyped-def]
        self.handler = handler
        self.requests: list[httpx.Request] = []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        self.requests.append(req)
        return self.handler(req)


def fred_handler(rows: list[dict] = ROWS, series: dict = SERIES):  # type: ignore[no-untyped-def]
    def handle(req: httpx.Request) -> httpx.Response:
        path = req.url.path
        if path == "/fred/series":
            return httpx.Response(200, json=series)
        if path == "/fred/series/observations":
            return httpx.Response(200, json=observations_body(rows))
        return httpx.Response(404, json={"error_code": 404, "error_message": "Not Found"})

    return handle


def make_adapter(handler, **kw) -> tuple[FredEvidenceAdapter, Rec]:  # type: ignore[no-untyped-def]
    rec = Rec(handler)
    client = FredClient(
        KEY, transport=httpx.MockTransport(rec), sleep=lambda _: None, min_interval=0.0, **kw
    )
    return FredEvidenceAdapter(SPEC, client, FrozenClock(NOW)), rec


# --- Parsing and timing ---------------------------------------------------------------


def test_parse_value() -> None:
    assert parse_value("320.4") == (Decimal("320.4"), EvidenceQuality.OK)
    assert parse_value(".") == (None, EvidenceQuality.MISSING)
    assert parse_value("") == (None, EvidenceQuality.MISSING)
    with pytest.raises(AdapterError):
        parse_value("abc")
    with pytest.raises(AdapterError):
        parse_value("Infinity")


def test_fetch_maps_vintages_and_release_time_dst() -> None:
    adapter, rec = make_adapter(fred_handler())
    result = adapter.fetch()
    assert result.errors == []
    obs = {(o.observation_date, o.vintage_date): o for o in result.observations}
    aug_rev = obs[(date(2026, 8, 1), date(2026, 10, 15))]
    assert aug_rev.value == Decimal("320.4")
    # Oct 15 2026 is EDT (UTC-4): 08:30 ET == 12:30 UTC
    assert aug_rev.available_at.astimezone(UTC) == datetime(2026, 10, 15, 12, 30, tzinfo=UTC)
    oct_missing = obs[(date(2026, 10, 1), date(2026, 11, 10))]
    assert oct_missing.value is None and oct_missing.quality is EvidenceQuality.MISSING
    # Nov 10 2026 is EST (UTC-5): 08:30 ET == 13:30 UTC
    assert oct_missing.available_at.astimezone(UTC) == datetime(2026, 11, 10, 13, 30, tzinfo=UTC)
    assert aug_rev.retrieved_at == NOW
    assert result.metadata and result.metadata.units == "Index 1982-1984=100"

    obs_req = rec.requests[-1].url.params
    assert obs_req["realtime_start"] == "1776-07-04" and obs_req["realtime_end"] == "9999-12-31"
    assert obs_req["output_type"] == "1" and obs_req["file_type"] == "json"
    assert all(r.method == "GET" for r in rec.requests)
    assert all(str(r.url).startswith("https://api.stlouisfed.org/fred/") for r in rec.requests)


def test_paging_by_offset() -> None:
    pages = {0: ROWS[:2], 2: ROWS[2:]}

    def handle(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/fred/series":
            return httpx.Response(200, json=SERIES)
        off = int(req.url.params["offset"])
        return httpx.Response(200, json=observations_body(pages[off], off, count=4))

    adapter, rec = make_adapter(handle)
    assert len(adapter.fetch().observations) == 4
    offsets = [r.url.params.get("offset") for r in rec.requests if "observations" in r.url.path]
    assert offsets == ["0", "2"]


def test_bad_row_is_reported_not_invented() -> None:
    rows = [*ROWS, {"realtime_start": "2026-11-10", "date": "2026-10-01x", "value": "1"}]
    adapter, _ = make_adapter(fred_handler(rows))
    result = adapter.fetch()
    assert len(result.observations) == 4
    assert len(result.errors) == 1 and result.errors[0].code == "BAD_RESPONSE"


def test_copyright_flag_added_to_license_notes() -> None:
    series = {**SERIES, "seriess": [{**SERIES["seriess"][0], "notes": "Copyright, 2026, X."}]}
    adapter, _ = make_adapter(fred_handler(series=series))
    result = adapter.fetch()
    assert result.metadata.copyright_flagged
    assert "COPYRIGHTED SERIES" in result.observations[0].license_notes


# --- Errors and secret handling --------------------------------------------------------


def test_invalid_key_shape_rejected_before_network() -> None:
    with pytest.raises(ValueError):
        FredClient("NOT-A-KEY")


def test_missing_key_fails_closed() -> None:
    with pytest.raises(AdapterError) as ei:
        FredClient.from_settings(Settings(_env_file=None))
    assert ei.value.code is AdapterErrorCode.SOURCE_UNAVAILABLE


def test_400_gives_friendly_message_without_echoing_upstream() -> None:
    adapter, _ = make_adapter(
        lambda _: httpx.Response(
            400, json={"error_code": 400, "error_message": f"Bad Request. api_key {KEY} bad"}
        )
    )
    with pytest.raises(AdapterError) as ei:
        adapter.fetch()
    assert "KRT_FRED_API_KEY" in str(ei.value)
    assert KEY not in str(ei.value)


def test_429_backoff_then_success_and_key_never_leaks(caplog: pytest.LogCaptureFixture) -> None:
    calls = {"n": 0}

    def handle(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, json={"error_code": 429, "error_message": "Too Many"})
        return fred_handler()(req)

    caplog.set_level(logging.DEBUG)
    sleeps: list[float] = []
    rec = Rec(handle)
    client = FredClient(KEY, transport=httpx.MockTransport(rec), sleep=sleeps.append,
                        min_interval=0.0, backoff_base=1.0)
    FredEvidenceAdapter(SPEC, client, FrozenClock(NOW)).fetch()
    assert sleeps == [1.0]
    assert KEY not in caplog.text


def test_timeout_error_does_not_chain_url_with_key() -> None:
    def boom(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout(f"timed out {req.url}", request=req)

    adapter, rec = make_adapter(boom, max_retries=1)
    with pytest.raises(AdapterError) as ei:
        adapter.fetch()
    err = ei.value
    assert err.code is AdapterErrorCode.NETWORK and len(rec.requests) == 2
    assert KEY not in str(err) and err.__cause__ is None and err.__suppress_context__


def test_path_allowlist() -> None:
    client = FredClient(KEY, transport=httpx.MockTransport(fred_handler()))
    with pytest.raises(ValueError):
        client.get("/category/children")


# --- Persistence, dedupe, point-in-time -----------------------------------------------


@pytest.fixture
def factory(settings: Settings):  # type: ignore[no-untyped-def]
    engine = make_engine(settings.database_url)
    yield make_session_factory(engine)
    engine.dispose()


def test_ingest_dedupes_and_records_runs(factory) -> None:  # type: ignore[no-untyped-def]
    clock = FrozenClock(NOW)
    s1 = run_evidence_ingestion(make_adapter(fred_handler())[0], factory, clock)
    s2 = run_evidence_ingestion(make_adapter(fred_handler())[0], factory, clock)
    assert (s1.status, s1.count) == ("success", 4)
    assert (s2.status, s2.count) == ("success", 0)  # nothing new; still a healthy refresh
    with factory() as s:
        assert s.scalar(select(func.count()).select_from(EvidenceRecord)) == 4
        assert s.scalar(select(func.count()).select_from(IngestionRun)) == 2


def test_new_vintage_appends_old_kept(factory) -> None:  # type: ignore[no-untyped-def]
    clock = FrozenClock(NOW)
    run_evidence_ingestion(make_adapter(fred_handler())[0], factory, clock)
    rows = [*ROWS, {"realtime_start": "2026-11-13", "date": "2026-10-01", "value": "322.0"}]
    s = run_evidence_ingestion(make_adapter(fred_handler(rows))[0], factory, clock)
    assert s.count == 1
    with factory() as sess:
        vintages = EvidenceRepository(sess).vintages_of("fred:CPIAUCSL", "2026-10-01")
        assert [(v.vintage_date, v.value) for v in vintages] == [
            ("2026-11-10", None), ("2026-11-13", Decimal("322.0"))]


def test_changed_content_for_stored_vintage_is_conflict_not_overwrite(factory) -> None:  # type: ignore[no-untyped-def]
    clock = FrozenClock(NOW)
    run_evidence_ingestion(make_adapter(fred_handler())[0], factory, clock)
    tampered = [dict(r) for r in ROWS]
    tampered[2]["value"] = "999.9"
    s = run_evidence_ingestion(make_adapter(fred_handler(tampered))[0], factory, clock)
    assert s.status == "partial" and s.errors[0].code == "VINTAGE_CONTENT_CHANGED"
    with factory() as sess:
        (sep,) = EvidenceRepository(sess).vintages_of("fred:CPIAUCSL", "2026-09-01")
        assert sep.value == Decimal("321.1")


def test_as_of_excludes_future_and_respects_release_time(factory) -> None:  # type: ignore[no-untyped-def]
    run_evidence_ingestion(make_adapter(fred_handler())[0], factory, FrozenClock(NOW))
    with factory() as s:
        repo = EvidenceRepository(s)

        def view(cutoff: datetime) -> dict[str, Decimal | None]:
            return {r.observation_date: r.value for r in repo.as_of("fred:CPIAUCSL", cutoff, 50)}

        assert view(datetime(2026, 9, 10, tzinfo=UTC)) == {}
        # Oct 15 08:00 EDT (12:00Z): revision not yet released -> first print
        assert view(datetime(2026, 10, 15, 12, 0, tzinfo=UTC)) == {"2026-08-01": Decimal("320.0")}
        # Oct 15 08:31 EDT: revision + September now known
        assert view(datetime(2026, 10, 15, 12, 31, tzinfo=UTC)) == {
            "2026-08-01": Decimal("320.4"), "2026-09-01": Decimal("321.1")}
        # Nov 10 after release: October present but MISSING (None), not zero
        latest = view(datetime(2026, 11, 10, 14, 0, tzinfo=UTC))
        assert "2026-10-01" in latest and latest["2026-10-01"] is None


def test_freshness() -> None:
    assert is_fresh(SPEC, NOW - timedelta(days=10), NOW)
    assert not is_fresh(SPEC, NOW - timedelta(days=46), NOW)
    assert not is_fresh(SPEC, None, NOW)


def test_unregistered_source_rejected_by_config() -> None:
    with pytest.raises(ValueError):
        Settings(_env_file=None, evidence_sources=["fred:ANYTHING"])


# --- API ------------------------------------------------------------------------------


def test_evidence_api(seeded: Settings) -> None:
    engine = make_engine(seeded.database_url)
    run_evidence_ingestion(make_adapter(fred_handler())[0], make_session_factory(engine),
                           FrozenClock(NOW))
    engine.dispose()
    app = create_app(seeded, FrozenClock(NOW))
    with TestClient(app, base_url="http://127.0.0.1") as c:
        sources = {s["id"]: s for s in c.get("/api/evidence/sources").json()["items"]}
        cpi = sources["fred:CPIAUCSL"]
        assert cpi["configured"] and cpi["record_count"] == 4
        assert cpi["latest_vintage"] == "2026-11-10" and cpi["is_fresh"] is True
        assert cpi["attribution"] == FRED_NOTICE
        assert cpi["last_run"]["status"] == "success"
        assert sources["fred:UNRATE"]["record_count"] == 0
        assert sources["fred:UNRATE"]["is_fresh"] is False

        r = c.get("/api/evidence/fred:CPIAUCSL/observations",
                  params={"as_of": "2026-10-15T12:31:00Z"}).json()
        assert [(i["observation_date"], i["value"]) for i in r["items"]] == [
            ("2026-09-01", "321.1"), ("2026-08-01", "320.4")]
        naive = c.get("/api/evidence/fred:CPIAUCSL/observations",
                      params={"as_of": "2026-10-15T12:31:00"})
        assert naive.status_code == 422  # timezone required

        v = c.get("/api/evidence/fred:CPIAUCSL/vintages",
                  params={"observation_date": "2026-08-01"}).json()
        assert [i["value"] for i in v["items"]] == ["320.0", "320.4"]

        assert c.get("/api/evidence/fred:NOPE/observations").status_code == 404
        assert c.get("/api/evidence/../observations").status_code == 404
        assert c.get("/api/collection-gaps").json() == {"items": []}
    app.state.engine.dispose()
