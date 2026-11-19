"""Optional headline search (Brave Search API) for "is there news that changes this?".

Off unless KRT_BRAVE_SEARCH_API_KEY is set. The key travels only in a request header (never
the URL), is a SecretStr, and is never logged or returned. Results are untrusted third-party
text: returned as plain strings, http(s) links only, and rendered as text by the UI.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

import httpx

from app.adapters.base import AdapterError
from app.adapters.http import RetryingJsonClient

BRAVE = "https://api.search.brave.com"
BRAVE_PATHS = re.compile(r"/res/v1/news/search")


def demojibake(t: str) -> str:
    """Repair UTF-8 that a publisher decoded as Windows-1252 ("â€“" -> "–"). Text that
    doesn't round-trip cleanly is returned unchanged."""
    if "â€" not in t and "Ã" not in t:
        return t
    try:
        return t.encode("cp1252").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return t


class NewsSearch:
    def __init__(self, api_key: str, *, transport: httpx.BaseTransport | None = None,
                 timeout: float = 10.0) -> None:
        self._http = RetryingJsonClient(BRAVE, allowed_bases={BRAVE}, path_pattern=BRAVE_PATHS,
                                        transport=transport, timeout=timeout, max_retries=1,
                                        min_interval=1.0)
        # Header, not query string: keeps the key out of URLs and any logged request line.
        self._http._http.headers["X-Subscription-Token"] = api_key

    def close(self) -> None:
        self._http.close()

    def search(self, q: str, count: int = 6) -> list[dict[str, Any]]:
        body = self._http.get("/res/v1/news/search", {"q": q, "count": count,
                                                       "freshness": "pw", "safesearch": "strict"})
        out = []
        for r in body.get("results") or []:
            url = str(r.get("url") or "")
            if urlparse(url).scheme not in ("http", "https"):
                continue
            out.append({"title": demojibake(str(r.get("title") or ""))[:200],
                        "url": url[:500],
                        "source": str((r.get("meta_url") or {}).get("hostname") or "")[:80],
                        "age": str(r.get("age") or "")[:40],
                        "description": demojibake(re.sub(r"<[^>]+>", "",
                                                         str(r.get("description") or "")))[:300]})
        return out


def headlines(settings: Any, subjects: list[str], prefix: str = "S", per: int = 3,
              limit: int = 5) -> list[dict[str, str]]:
    """Recent headlines about each subject, with ids (S1, S2...) the model can cite.
    Empty when no Brave key is set. A failing subject is skipped, never fatal."""
    key =settings.brave_search_api_key
    if key is None or not subjects:
        return []
    out: list[dict[str, str]] = []
    client = NewsSearch(key.get_secret_value(), timeout=settings.http_timeout_seconds)
    try:
        for name in subjects[:limit]:
            try:
                for it in client.search(f"{name} NBA", count=per):
                    out.append({"id": f"{prefix}{len(out) + 1}", "about": name,
                                "title": it["title"], "source": it["source"], "age": it["age"],
                                "snippet": it["description"], "url": it["url"]})
            except AdapterError:
                continue
    finally:
        client.close()
    return out
