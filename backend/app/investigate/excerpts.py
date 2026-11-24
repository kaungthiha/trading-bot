"""User-provided excerpts: text the user pasted from something they read (Phase 4, stream 3).

Rules (sources.py "user_excerpt", rights status manual_user_input):
- The app never fetches the link the user gives; it's kept only so the user can find the
  source again. Pasting text is not permission to crawl the publisher.
- An excerpt is shown as "user-provided, unverified" until another source agrees: a model
  claim resting only on excerpts (U1, U2...) is always marked unverified.
- It's processed locally only (deterministic checks; the local model if the user runs it).
- It's the user's own local note, so it isn't on Brave's retention clock: it stays with the
  investigation until the user removes it, and it carries over when the research is
  refreshed. Anything written from news is still purged on schedule.

How a change is applied: the result keeps a snapshot of its summary and details from before
any excerpt (`excerpt_base`); every add or remove rebuilds from that snapshot, so model
claims don't pile up and removing the last excerpt restores the original exactly.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.investigate import schemas as S
from app.investigate import search

MAX_EXCERPTS = 5
MIN_TEXT, MAX_TEXT = 20, 4000
URL = re.compile(r"^https?://[^\s<>\"']{3,490}$", re.I)
COVERAGE_TAG = "you pasted"


class ExcerptIn(BaseModel):
    text: str = Field(min_length=MIN_TEXT, max_length=MAX_TEXT)
    source: str = Field(min_length=1, max_length=120)
    url: str | None = Field(default=None, max_length=500)
    published_on: date | None = None

    @field_validator("text", "source")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", v).strip()
        if not v:
            raise ValueError("must not be blank")
        return v

    @field_validator("url")
    @classmethod
    def _url(cls, v: str | None) -> str | None:
        v = (v or "").strip()
        if not v:
            return None
        if not URL.match(v):
            raise ValueError("must be an http(s) link")
        return v


class Unsupported(ValueError):
    pass


def excerpts_of(r: S.Result) -> list[S.Source]:
    return [s for s in r.sources if s.access == "user_provided"]


def _snapshot(r: S.Result) -> S.ExcerptBase:
    return S.ExcerptBase(
        summary=r.summary.model_copy(deep=True),
        details=r.details.model_copy(deep=True),
        model=r.processing.model,
        partial_reasons=list(r.processing.partial_reasons),
        errors=list(r.processing.errors),
    )


def restore_base(r: S.Result) -> S.Result:
    """r with the excerpt-free summary and details put back (sources unchanged)."""
    out = r.model_copy(deep=True)
    b = out.excerpt_base
    if b is not None:
        out.summary = b.summary.model_copy(deep=True)
        out.details = b.details.model_copy(deep=True)
        out.processing.model = b.model
        out.processing.partial_reasons = list(b.partial_reasons)
        out.processing.errors = list(b.errors)
        out.excerpt_base = None
    return out


def _flags(h: S.Hypothesis, s: S.Source) -> list[str]:
    text = s.excerpt or ""
    out = []
    if search.sport_mismatch(h, text):
        out.append(f"it doesn't read like {h.sport} coverage")
    if s.line_match == "different_line":
        out.append("it mentions a different line, so it isn't direct support")
    day = search.game_date(h.event_ticker)
    if day is not None and s.published_at:
        try:
            pub = date.fromisoformat(s.published_at[:10])
        except ValueError:
            pub = None
        if pub is not None and pub > day.date() + timedelta(days=1):
            out.append("it's dated after this game")
        elif pub is not None and pub < day.date() - search.PAST_MATCHUP:
            out.append("it's dated well before this game, so it may be about an earlier meeting")
    return out


def decorate(r: S.Result) -> S.Result:
    """Snapshot the excerpt-free state, then add one deterministic finding per excerpt and
    the coverage tag. Never quotes the excerpt itself."""
    out = r.model_copy(deep=True)
    ex = excerpts_of(out)
    if not ex:
        out.excerpt_base = None
        return out
    out.excerpt_base = _snapshot(out)
    for s in ex:
        flags = _flags(out.hypothesis, s)
        when = f", dated {s.published_at[:10]}" if s.published_at else ", no date given"
        out.details.against.append(
            S.Finding(
                text=(
                    f"You added an excerpt from {s.publisher}{when}: user-provided and "
                    "unverified until another source agrees"
                    + (f"; {'; '.join(flags)}" if flags else "")
                    + "."
                )[:400],
                kind="interpretation",
                stance="neutral",
                source_ids=[s.id],
                verified=False,
            )
        )
    n = len(ex)
    tag = f"{n} excerpt{'s' if n != 1 else ''} {COVERAGE_TAG}"
    parts = [p for p in (out.summary.coverage or "").split(" · ") if p and COVERAGE_TAG not in p]
    parts.insert(min(2, len(parts)), tag)
    out.summary.coverage = " · ".join(parts)[:200]
    return out


def rebuild(r: S.Result, chat: Any = None) -> S.Result:
    """Recompute everything that depends on excerpts from the excerpt-free snapshot. With a
    local model, re-summarise: news snippets aren't stored, so news counts as headlines."""
    from app.investigate import synth

    out = decorate(restore_base(r))
    ex = excerpts_of(out)
    if not ex or chat is None:
        return out
    base = out.excerpt_base
    done = synth.apply(out, {s.id: s.excerpt or "" for s in ex}, chat)
    done.excerpt_base = base

    def runs(x: S.Result) -> int:
        return sum(1 for m in x.details.methodology if m.startswith("Summary: local model"))

    if runs(done) <= runs(out):  # the model was busy or failed: keep the app's own summary
        return done
    done.details.methodology.append(
        "Re-summarised locally after you added an excerpt. News snippets aren't stored, so "
        "news articles count as headlines only in this summary; claims resting only on your "
        "excerpt stay unverified."
    )
    if "user_excerpts" not in done.processing.partial_reasons:
        done.processing.partial_reasons.append("user_excerpts")
    return done


def add(r: S.Result, inp: ExcerptIn, now: datetime, chat: Any = None) -> S.Result:
    ex = excerpts_of(r)
    if len(ex) >= MAX_EXCERPTS:
        raise Unsupported(f"At most {MAX_EXCERPTS} excerpts per investigation.")
    used = {s.id for s in r.sources}
    sid = next(f"U{i}" for i in range(1, 100) if f"U{i}" not in used)
    h = r.hypothesis
    line = "unknown" if search.sport_mismatch(h, inp.text) else search.line_match(h, inp.text)
    src = S.Source(
        id=sid,
        url=inp.url or "",
        title=f"Excerpt you pasted from {inp.source}"[:200],
        publisher=inp.source,
        published_at=inp.published_on.isoformat() if inp.published_on else None,
        retrieved_at=now.isoformat(),
        access="user_provided",
        line_match=line,  # type: ignore[arg-type]
        excerpt=inp.text,
    )
    out = r.model_copy(deep=True)
    out.sources.append(src)
    return rebuild(out, chat)


def remove(r: S.Result, sid: str, chat: Any = None) -> S.Result:
    if not any(s.id == sid for s in excerpts_of(r)):
        raise KeyError(sid)
    out = r.model_copy(deep=True)
    out.sources = [s for s in out.sources if s.id != sid]
    return rebuild(out, chat)


def carry(old: S.Result, new: S.Result, chat: Any = None) -> S.Result:
    """Keep the user's excerpts when the research is refreshed."""
    ex = excerpts_of(old)
    if not ex:
        return new
    out = new.model_copy(deep=True)
    used = {s.id for s in out.sources}
    out.sources.extend(s.model_copy() for s in ex if s.id not in used)
    return rebuild(out, chat)
