"""Publisher registry: what this app may do with each source's content.

Discovery is only through Brave News Search results (headline, link, short snippet, date).
The app NEVER fetches a publisher's page itself, so no robots/paywall/CAPTCHA question
arises, and no full article is read or stored.

Full-text processing needs a licence or an approved feed. As of this version NO publisher
below has granted one, so every entry is `full_text="not_permitted"`. The UI says
"headline only" / "headline and snippet" accordingly and never implies an article was read.

Retention, for every source:
- the headline, link, publisher and publication time are stored with the investigation;
- the snippet is used transiently (in memory, for matching and the local summary), never
  written to disk. Brave's terms allow only transient storage of search results.

Bump REGISTRY_VERSION when anything here changes: it is part of the investigation cache key.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

REGISTRY_VERSION = "2026-11-23.1"


@dataclass(frozen=True)
class Publisher:
    name: str
    kind: Literal["official", "news", "injury_news", "betting_analysis"]
    priority: int  # 1 = most weight when trimming to the source limit
    full_text: Literal["not_permitted", "licensed_feed"] = "not_permitted"
    discovery: str = "brave_news_metadata"
    retention: str = "headline+link stored; snippet transient (not stored)"
    attribution: str = "publisher name and link to the original article"
    enabled: bool = True
    note: str = ""


REGISTRY: dict[str, Publisher] = {
    # Official league / team sources
    "nba.com": Publisher("NBA.com", "official", 1),
    "wnba.com": Publisher("WNBA.com", "official", 1),
    "ncaa.com": Publisher("NCAA.com", "official", 1),
    "nhl.com": Publisher("NHL.com", "official", 1,
                         note="Headline only: the app never fetches NHL.com (its terms bar "
                         "unauthorised automated access)."),
    "nfl.com": Publisher("NFL.com", "official", 1,
                         note="Headline only: the app never fetches NFL.com."),
    # Football news and injury reporting (metadata via Brave only)
    "profootballtalk.nbcsports.com": Publisher("ProFootballTalk", "injury_news", 1),
    "profootballnetwork.com": Publisher("Pro Football Network", "news", 2),
    # Hockey news and goalie reporting (metadata via Brave only)
    "dailyfaceoff.com": Publisher("Daily Faceoff", "injury_news", 1,
                                  note="Reports projected goalies: always 'reported', never "
                                  "an official confirmation."),
    "sportsnet.ca": Publisher("Sportsnet", "news", 2),
    "tsn.ca": Publisher("TSN", "news", 2),
    "thehockeynews.com": Publisher("The Hockey News", "news", 2),
    # News and injury reporting
    "espn.com": Publisher("ESPN", "news", 1),
    "apnews.com": Publisher("AP News", "news", 1),
    "rotowire.com": Publisher("RotoWire", "injury_news", 1),
    "cbssports.com": Publisher("CBS Sports", "news", 2),
    "nbcsports.com": Publisher("NBC Sports", "news", 2),
    "theathletic.com": Publisher("The Athletic", "news", 2, note="Paywalled: headline only."),
    "nytimes.com": Publisher("The New York Times", "news", 2, note="Paywalled: headline only."),
    "foxsports.com": Publisher("FOX Sports", "news", 2),
    "si.com": Publisher("Sports Illustrated", "news", 2),
    # Betting analysis (opinion: always classed as analyst opinion, never fact)
    "covers.com": Publisher("Covers", "betting_analysis", 3),
    "pickswise.com": Publisher("Pickswise", "betting_analysis", 3),
    "boydsbets.com": Publisher("Boyd's Bets", "betting_analysis", 3),
    "pickdawgz.com": Publisher("PickDawgz", "betting_analysis", 3),
    "sportsbettingdime.com": Publisher("Sports Betting Dime", "betting_analysis", 3),
    "sportsbookreview.com": Publisher("Sportsbook Review", "betting_analysis", 3),
    "actionnetwork.com": Publisher("Action Network", "betting_analysis", 3),
}

UNKNOWN = Publisher(
    "(unlisted publisher)", "news", 4, note="Not reviewed: headline/snippet only, lowest weight."
)


def lookup(hostname: str) -> tuple[str, Publisher]:
    """(registered domain, publisher) for a hostname like 'www.covers.com' or 'm.espn.com'."""
    h = hostname.lower().strip(".")
    parts = h.split(".")
    for i in range(len(parts) - 1):
        dom = ".".join(parts[i:])
        if dom in REGISTRY:
            return dom, REGISTRY[dom]
    return ".".join(parts[-2:]) if len(parts) >= 2 else h, UNKNOWN


def full_text_allowed() -> list[str]:
    """Publishers whose licence allows article-level processing (currently none)."""
    return [d for d, p in REGISTRY.items() if p.full_text == "licensed_feed" and p.enabled]
