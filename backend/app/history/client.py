"""Signed, READ-ONLY client for your own Kalshi account.

Safety properties (enforced here and tested):
- Only GET is implemented. There is no code path that can create, amend or cancel orders.
- Only an explicit allow-list of history endpoints can be called.
- Only Kalshi's REST hosts are accepted; redirects are not followed.
- Keys come from .env (key id as SecretStr; private key file outside the repo) and are
  never logged or returned. Use a key created with READ scope only.

Docs read 2026-11-18: api-reference/portfolio/{get-fills,get-settlements,get-positions,
get-balance}, api-reference/historical/{get-historical-fills,get-historical-positions},
getting_started/{api_keys,rate_limits,pagination,historical_data}.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import httpx

from app.core.config import KALSHI_REST_BASES, Settings
from app.execution.signing import API_PREFIX, Signer

READ_PATHS = frozenset({
    "/portfolio/fills", "/portfolio/settlements", "/portfolio/positions",
    "/portfolio/balance", "/historical/fills", "/historical/positions",
})
_HOSTS = {httpx.URL(u).host for u in KALSHI_REST_BASES.values()}
USER_AGENT = "krt-local-research/0.1 (read-only account history)"


class AccountError(Exception):
    pass


class AccountReader:
    def __init__(self, signer: Signer, base_url: str, *,
                 transport: httpx.BaseTransport | None = None, timeout: float = 15.0,
                 clock_ms: Callable[[], int] = lambda: int(time.time() * 1000),
                 sleep: Callable[[float], None] = time.sleep, min_interval: float = 0.1,
                 max_retries: int = 3) -> None:
        url = httpx.URL(base_url)
        if url.scheme != "https" or url.host not in _HOSTS or not base_url.endswith(API_PREFIX):
            raise ValueError("Account history only talks to Kalshi's REST API over HTTPS")
        self._signer, self._clock_ms, self._sleep = signer, clock_ms, sleep
        self._min_interval, self._max_retries = min_interval, max_retries
        self._last = 0.0
        self._http = httpx.Client(base_url=base_url, timeout=timeout, transport=transport,
                                  follow_redirects=False,
                                  headers={"Accept": "application/json",
                                           "User-Agent": USER_AGENT})

    def __repr__(self) -> str:
        return "AccountReader(<redacted>)"

    @classmethod
    def from_settings(cls, s: Settings, **kw: Any) -> AccountReader:
        if s.kalshi_api_key_id is None or s.kalshi_private_key_path is None:
            raise AccountError("Add KRT_KALSHI_API_KEY_ID and KRT_KALSHI_PRIVATE_KEY_PATH to "
                               ".env (a READ-only key; see the README)")
        path = s.kalshi_private_key_path
        if not path.is_file():
            raise AccountError("The private key file in KRT_KALSHI_PRIVATE_KEY_PATH was not "
                               "found")
        try:
            signer = Signer.from_pem_file(s.kalshi_api_key_id.get_secret_value(), path)
        except (ValueError, TypeError) as e:
            raise AccountError(f"Could not load the private key: {type(e).__name__}") from None
        return cls(signer, s.kalshi_rest_base, **kw)

    def close(self) -> None:
        self._http.close()

    def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if path not in READ_PATHS:
            raise ValueError(f"{path} is not an allow-listed read endpoint")
        for attempt in range(self._max_retries + 1):
            wait = self._min_interval - (time.monotonic() - self._last)
            if wait > 0:
                self._sleep(wait)
            req = self._http.build_request("GET", path, params=params)
            req.headers.update(self._signer.headers(self._clock_ms(), "GET", req.url.path))
            try:
                r = self._http.send(req)
            except httpx.HTTPError as e:
                if attempt < self._max_retries:
                    self._sleep(2 ** attempt)
                    continue
                raise AccountError(f"network error: {type(e).__name__}") from None
            finally:
                self._last = time.monotonic()
            if r.status_code == 200:
                body = r.json()
                if not isinstance(body, dict):
                    raise AccountError("unexpected response shape")
                return body
            if (r.status_code == 429 or r.status_code >= 500) and attempt < self._max_retries:
                self._sleep(2 ** attempt)
                continue
            if r.status_code in (401, 403):
                raise AccountError(
                    f"Kalshi refused the key (HTTP {r.status_code}). Check the key id, the "
                    "key file, that the key has READ scope, and that your PC clock is right.")
            raise AccountError(f"Kalshi returned HTTP {r.status_code} for {path}")
        raise AccountError("retries exhausted")  # pragma: no cover

    def paginate(self, path: str, key: str, params: dict[str, Any] | None = None,
                 max_pages: int = 500) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        cursor = ""
        for _ in range(max_pages):
            p = {**(params or {}), "limit": 1000}
            if cursor:
                p["cursor"] = cursor
            body = self.get(path, p)
            items = body.get(key)
            if not isinstance(items, list):
                raise AccountError(f"missing '{key}' in {path}")
            out.extend(i for i in items if isinstance(i, dict))
            cursor = body.get("cursor") or ""
            if not cursor:
                return out
        raise AccountError(f"{path}: more than {max_pages} pages; stopped")
