"""Shared hardened JSON-over-HTTPS GET client for external read-only sources.

Properties: GET only; base URL must be in an explicit allowlist; path must match an
allowlist regex; no redirects; minimum spacing between requests; bounded exponential
backoff on 429/5xx/timeouts. Error messages never include URLs or query strings (which
may carry API keys).
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable, Collection
from typing import Any

import httpx

from app.adapters.base import AdapterError, AdapterErrorCode
from app.core.logging import RedactingFilter

# httpx logs full request URLs (including query-string API keys) at INFO. Attach the
# redaction filter to its loggers directly so this holds regardless of how logging is
# configured (tests, uvicorn, debug mode). Idempotent across re-imports.
for _name in ("httpx", "httpcore"):
    _lg = logging.getLogger(_name)
    if not any(isinstance(f, RedactingFilter) for f in _lg.filters):
        _lg.addFilter(RedactingFilter())


class RetryingJsonClient:
    def __init__(
        self,
        base_url: str,
        *,
        allowed_bases: Collection[str],
        path_pattern: re.Pattern[str],
        timeout: float = 10.0,
        max_retries: int = 4,
        min_interval: float = 0.25,
        backoff_base: float = 0.5,
        backoff_cap: float = 8.0,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        default_params: dict[str, str] | None = None,
        user_agent: str = "krt-local-research/0.1 (read-only)",
    ) -> None:
        if base_url not in allowed_bases:
            raise ValueError("Base URL is not an allowlisted host for this source")
        self._path_pattern = path_pattern
        self._default_params = dict(default_params or {})
        self._http = httpx.Client(
            base_url=base_url,
            timeout=timeout,
            transport=transport,
            follow_redirects=False,
            headers={"Accept": "application/json", "User-Agent": user_agent},
        )
        self._max_retries = max_retries
        self._min_interval = min_interval
        self._backoff_base = backoff_base
        self._backoff_cap = backoff_cap
        self._sleep = sleep
        self._monotonic = monotonic
        self._last_request: float | None = None
        self.request_count = 0

    def close(self) -> None:
        self._http.close()

    def __enter__(self):  # type: ignore[no-untyped-def]
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # Hooks for subclasses -----------------------------------------------------------
    def _check_request(self, request: httpx.Request) -> None:
        """Raise to refuse sending a request (e.g. it carries forbidden headers)."""

    # Internals ----------------------------------------------------------------------
    def _throttle(self) -> None:
        now = self._monotonic()
        if self._last_request is not None:
            wait = self._min_interval - (now - self._last_request)
            if wait > 0:
                self._sleep(wait)
        self._last_request = self._monotonic()

    def _backoff(self, attempt: int) -> None:
        self._sleep(min(self._backoff_base * (2**attempt), self._backoff_cap))

    def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self._path_pattern.fullmatch(path):
            raise ValueError(f"Path not in read-only allowlist: {path!r}")
        merged = {**(params or {}), **self._default_params}
        attempt = 0
        while True:
            self._throttle()
            request = self._http.build_request("GET", path, params=merged)
            self._check_request(request)
            self.request_count += 1
            try:
                resp = self._http.send(request)
            except httpx.TimeoutException:
                # `from None`: httpx exceptions embed the request URL (may contain keys).
                if attempt >= self._max_retries:
                    raise AdapterError("Request timed out", AdapterErrorCode.NETWORK) from None
                self._backoff(attempt)
                attempt += 1
                continue
            except httpx.TransportError:
                if attempt >= self._max_retries:
                    raise AdapterError("Network error", AdapterErrorCode.NETWORK) from None
                self._backoff(attempt)
                attempt += 1
                continue

            status = resp.status_code
            if status == 429 or status >= 500:
                if attempt >= self._max_retries:
                    code = (
                        AdapterErrorCode.RATE_LIMITED
                        if status == 429
                        else AdapterErrorCode.UPSTREAM_ERROR
                    )
                    raise AdapterError(f"Upstream returned {status}", code, status)
                self._backoff(attempt)
                attempt += 1
                continue
            if status == 404:
                raise AdapterError("Not found", AdapterErrorCode.NOT_FOUND, status)
            if status >= 300:
                raise AdapterError(
                    f"Upstream returned {status}", AdapterErrorCode.HTTP_ERROR, status
                )
            try:
                body = resp.json()
            except ValueError:
                raise AdapterError(
                    "Response was not JSON", AdapterErrorCode.BAD_RESPONSE
                ) from None
            if not isinstance(body, dict):
                raise AdapterError("Unexpected response shape", AdapterErrorCode.BAD_RESPONSE)
            return body
