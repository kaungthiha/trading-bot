"""Data-source registry: what this app may do with each source, from a dated review.

A site being public is NOT a licence to scrape it, feed it to a model, or keep its text.
Every source below records exactly which operations its published terms allow for this
app's use (a single person's local, non-commercial research tool). Adapters must call
`allows(source_id, operation)` before any request; nothing is silently promoted from
`metadata_only` to full text. When a review is uncertain the source is
`blocked_pending_review` and only links are offered for manual reading.

rights_status:
- structured_dataset_allowed: a published file/API whose terms support the intended use;
- metadata_only: titles, links and discovery results only (snippets per provider terms);
- licensed_full_text: automated processing and retention under a reviewed licence (none yet);
- manual_user_input: text the user pastes; never a licence to crawl the publisher;
- blocked_pending_review: no automatic ingestion;
- legacy_unreviewed: in use before this registry (owner-accepted), terms not re-reviewed here;
  kept for the features that already rely on it, never used for a new sport or purpose.

Owner switch: KRT_RESEARCH_DISABLED_SOURCES=moneypuck,espn_site_api (comma-separated ids)
turns a source off without code changes. Bump SOURCES_VERSION when anything changes.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

SOURCES_VERSION = "2026-11-23.5"
REVIEWED = "2026-11-21"
NFL_REVIEWED = "2026-11-23"

Rights = Literal[
    "structured_dataset_allowed",
    "metadata_only",
    "licensed_full_text",
    "manual_user_input",
    "blocked_pending_review",
    "legacy_unreviewed",
]


@dataclass(frozen=True)
class DataSource:
    source_id: str
    name: str
    sport: str
    information_type: str
    connector: str  # module that talks to it, or "none" (not connected)
    usage_terms_url: str
    rights_status: Rights
    allowed_operations: tuple[str, ...]
    attribution: str
    expiry: str  # when stored content must go, or "n/a"
    last_reviewed_at: str
    notes: str
    review_quotes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["allowed_operations"] = list(self.allowed_operations)
        d["review_quotes"] = list(self.review_quotes)
        return d


SOURCES: dict[str, DataSource] = {
    s.source_id: s
    for s in [
        DataSource(
            "kalshi_public",
            "Kalshi public market data",
            "all",
            "markets, prices, settlement rules",
            "app.adapters.kalshi_public",
            "https://docs.kalshi.com",
            "structured_dataset_allowed",
            ("read_markets", "read_rules"),
            "Kalshi",
            "n/a",
            REVIEWED,
            "The exchange's own documented public API; the app reads it and never trades.",
        ),
        DataSource(
            "brave_news",
            "Brave News Search",
            "all",
            "news discovery (headline, link, short snippet, date)",
            "app.sportsdata.news",
            "https://brave.com/search/api/",
            "metadata_only",
            ("search_metadata", "transient_snippet_for_matching_and_local_summary"),
            "Publisher name and link to the original article",
            "Headline/link removed from stored investigations after the search cache window; "
            "snippets never stored",
            REVIEWED,
            "Every request counts against the one app-wide cap (100/day, 2000/month by default). "
            "Brave's terms allow only transient storage of results.",
        ),
        DataSource(
            "espn_site_api",
            "ESPN public site JSON",
            "basketball (NBA, WNBA, NCAA)",
            "schedules, box scores, injury report",
            "app.sportsdata.espn",
            "https://disneytermsofuse.com/",
            "legacy_unreviewed",
            ("basketball_box_scores", "basketball_injury_report"),
            "ESPN",
            "In-memory cache only",
            REVIEWED,
            "Undocumented public endpoints the basketball features already used before this "
            "registry. Not reviewed or licensed for automated use here; deliberately NOT "
            "used for hockey or any new sport. Turn off with KRT_SPORTS_EVIDENCE_ENABLED=false.",
        ),
        DataSource(
            "moneypuck",
            "MoneyPuck season data downloads",
            "hockey (NHL)",
            "team and goalie season stats: expected goals, goals for/against, goalie "
            "goals saved above expected",
            "app.sportsdata.moneypuck",
            "https://moneypuck.com/data.htm",
            "structured_dataset_allowed",
            ("download_listed_season_csv", "download_listed_game_logs"),
            "Data: MoneyPuck.com (credited wherever its numbers appear)",
            "In-memory cache only (refreshed at most every 12 hours)",
            REVIEWED,
            "Allowed for non-commercial use with credit: this app is one person's local "
            "research tool and doesn't sell or republish the data. Only files the data page "
            "lists are downloaded, at most twice a day: the two season CSVs (teams, goalies) "
            "and, since Nov 23, the season's goalie and skater game-by-game zips (linked from "
            "the same page on MoneyPuck's download host peter-tanner.com) for rest days and "
            "missed games. No other page is fetched (non-approved scraping is blocked). "
            "Owner to confirm the personal, non-commercial reading; any commercial use "
            "needs MoneyPuck's permission.",
            (
                "The data below is free to use for non-commercial purposes and by "
                "journalists for ad-hoc use.",
                "Please clearly credit MoneyPuck.com in all cases where you are showing "
                "anything using our data as an input.",
                "Please message us for approval before scraping any data not listed on this page.",
            ),
        ),
        DataSource(
            "nhl_api_web",
            "NHL web data endpoints (api-web.nhle.com)",
            "hockey (NHL)",
            "schedules, rosters, box scores, play-by-play",
            "none",
            "https://www.nhl.com/info/terms-of-service",
            "blocked_pending_review",
            (),
            "NHL",
            "n/a",
            REVIEWED,
            "No published documentation or terms for these endpoints, and NHL.com's terms "
            "prohibit unauthorised automated means to compile information. Needs written "
            "permission or an official licensed feed before any use.",
            (
                "Engage in unauthorized spidering, scraping, or harvesting of content or "
                "information, or use any other unauthorized automated means to compile "
                "information;",
            ),
        ),
        DataSource(
            "puckapi",
            "PuckAPI",
            "hockey (NHL)",
            "normalised team and goalie data (500 free credits/month advertised)",
            "none",
            "https://puckapi.com/",
            "blocked_pending_review",
            (),
            "PuckAPI",
            "n/a",
            REVIEWED,
            "Not reviewed: needs an account key, its terms page and quota checked first.",
        ),
        DataSource(
            "open_meteo",
            "Open-Meteo weather API",
            "outdoor sports",
            "kickoff forecast for open-air NFL stadiums",
            "app.sportsdata.weather",
            "https://open-meteo.com/en/terms",
            "structured_dataset_allowed",
            ("forecast_lookup_noncommercial",),
            "Weather data by Open-Meteo.com (CC BY 4.0)",
            "n/a",
            REVIEWED,
            "Allowed for non-commercial use under CC BY 4.0, under 10,000 calls/day. One "
            "request per NFL game (cached an hour), only for home teams' open-air stadiums "
            "within 7 days of kickoff; no key needed.",
            (
                "You may only use the free API services for non-commercial purposes.",
                "Less than 10'000 API calls per day, 5'000 per hour and 600 per minute.",
            ),
        ),
        DataSource(
            "nflverse_schedules",
            "nflverse schedules release (games.csv)",
            "football (NFL)",
            "game facts: kickoff, final scores, rest days, roof, stadium, listed starting QB",
            "app.sportsdata.nflverse",
            "https://github.com/nflverse/nflverse-data/releases/tag/schedules",
            "structured_dataset_allowed",
            ("download_schedule_release",),
            "Data: nflverse (CC BY 4.0), linked to the release page",
            "In-memory cache only (refreshed at most every 12 hours)",
            NFL_REVIEWED,
            "Hosted in the CC BY 4.0 nflverse-data repository; maintained in Lee Sharpe's "
            "nfldata repo, which has no licence file of its own. Only public game facts are "
            "read. The sportsbook columns (moneylines, spread_line, total_line, odds) are "
            "never read: they come from betting sources this registry hasn't reviewed. The "
            "listed QB for an upcoming game is a projection, never an official lineup.",
            (
                "nflverse-data repository licence: Creative Commons Attribution 4.0 "
                "International (CC-BY-4.0).",
            ),
        ),
        DataSource(
            "nflverse_team_stats",
            "nflverse team stats release (stats_team_week_{season}.csv)",
            "football (NFL)",
            "weekly team totals incl. passing/rushing EPA and plays",
            "app.sportsdata.nflverse",
            "https://github.com/nflverse/nflverse-data/releases/tag/stats_team",
            "structured_dataset_allowed",
            ("download_team_stats_release",),
            "Data: nflverse (CC BY 4.0), linked to the release page",
            "In-memory cache only (refreshed at most every 12 hours)",
            NFL_REVIEWED,
            "nflverse's own aggregates (nflfastR calculate_stats) in the CC BY 4.0 repository. "
            "Used for points-independent efficiency (EPA per play), point in time.",
            ("Team stats in different summary levels created with nflfastR::calculate_stats()",),
        ),
        DataSource(
            "nflverse_player_stats",
            "nflverse player stats release (stats_player_week_{season}.csv)",
            "football (NFL)",
            "weekly player stat lines (passing, rushing, receiving, touchdowns)",
            "app.sportsdata.nflverse",
            "https://github.com/nflverse/nflverse-data/releases/tag/stats_player",
            "structured_dataset_allowed",
            ("download_player_stats_release",),
            "Data: nflverse (CC BY 4.0), linked to the release page",
            "In-memory cache only (refreshed at most every 12 hours)",
            NFL_REVIEWED,
            "nflverse's own aggregates (nflfastR calculate_stats) in the CC BY 4.0 repository, "
            "used for player-prop frequencies, point in time. Downloaded only when a prop is "
            "investigated. A player has a row only for games with a recorded stat, so games "
            "without one (inactive, or no catch/carry) are reported, never silently skipped.",
            (
                "Player stats in different summary levels created with "
                "`nflfastR::calculate_stats()`",
            ),
        ),
        DataSource(
            "nflverse_injuries",
            "nflverse injuries release (injuries_{season}.csv)",
            "football (NFL)",
            "the NFL's weekly injury report: player, position, game status, practice status",
            "app.sportsdata.nflverse",
            "https://github.com/nflverse/nflverse-data/releases/tag/injuries",
            "structured_dataset_allowed",
            ("download_injury_report_release",),
            "Data: nflverse (CC BY 4.0); the report itself is the NFL's",
            "In-memory cache only (refreshed at most every 12 hours)",
            NFL_REVIEWED,
            "The official report republished by nflverse; NFL.com is never fetched. Only "
            "status facts are used, tagged with the report week. nflreadr notes NFL data "
            "belongs to its owners, so the owner should confirm this personal, non-commercial "
            "use; switch off with KRT_RESEARCH_DISABLED_SOURCES=nflverse_injuries. The file "
            "often lags a week: a missing week is shown as unknown, never as healthy.",
            (
                "NFL data accessed by this package belong to their respective owners, and are "
                "governed by their terms of use. (nflreadr)",
            ),
        ),
        DataSource(
            "nflverse_ftn",
            "nflverse FTN charting release",
            "football (NFL)",
            "charted play details",
            "none",
            "https://github.com/nflverse/nflverse-data/releases/tag/ftn_charting",
            "blocked_pending_review",
            (),
            "FTN Data via nflverse",
            "n/a",
            NFL_REVIEWED,
            "Under a different licence (CC BY-SA 4.0 per the spec) that hasn't been "
            "confirmed for this use; never downloaded.",
        ),
        DataSource(
            "statsbomb_open",
            "StatsBomb Open Data",
            "soccer",
            "historical event data for selected competitions",
            "none",
            "https://github.com/hudl/open-data",
            "blocked_pending_review",
            (),
            "StatsBomb (name and logo required)",
            "n/a",
            REVIEWED,
            "README requires crediting StatsBomb with its logo; the LICENSE.pdf couldn't be "
            "read, so its terms (including any AI/data-mining clause) are unverified.",
        ),
        DataSource(
            "ncaa_api_community",
            "NCAA API (community wrapper)",
            "college sports",
            "scores, box scores, schedules",
            "none",
            "https://github.com/henrygd/ncaa-api",
            "blocked_pending_review",
            (),
            "NCAA",
            "n/a",
            REVIEWED,
            "The wrapper's code licence isn't a licence to NCAA's data; NCAA terms unreviewed.",
        ),
        DataSource(
            "sports_insights_rss",
            "Sports Insights RSS",
            "several",
            "betting-oriented article discovery",
            "none",
            "https://www.sportsinsights.com/sports-insights-rss-feed/",
            "metadata_only",
            (),
            "Publisher name and link",
            "n/a",
            REVIEWED,
            "At most titles and links for discovery; feed terms not reviewed, so not connected.",
        ),
        DataSource(
            "cbs_rss",
            "CBS Sports RSS",
            "several",
            "news discovery",
            "none",
            "https://www.cbssports.com/xml/rss",
            "metadata_only",
            (),
            "Publisher name and link",
            "n/a",
            REVIEWED,
            "At most titles and links; feed terms not reviewed, so not connected.",
        ),
        DataSource(
            "user_excerpt",
            "Excerpts you paste into an investigation",
            "all",
            "text you copied from something you read, with its source and date",
            "app.investigate.excerpts",
            "n/a",
            "manual_user_input",
            ("process_pasted_text_locally",),
            "The source name and link you give",
            "Kept with the investigation until you remove it (your own local note)",
            NFL_REVIEWED,
            "Processed on this computer only (deterministic checks; the local model if you "
            "use one). The link is never fetched, and a paste is not permission to crawl the "
            "publisher. Always shown as user-provided and unverified until another source "
            "agrees; at most 5 per investigation, 4,000 characters each.",
        ),
        DataSource(
            "football_data_org",
            "football-data.org API (free tier)",
            "soccer (Premier League, La Liga, Bundesliga, Serie A, Ligue 1, Champions League)",
            "fixtures, kickoff times, 90-minute results",
            "app.sportsdata.footballdata",
            "https://www.football-data.org/client/register",
            "structured_dataset_allowed",
            ("read_competition_matches",),
            "Football data provided by the Football-Data.org API",
            "In-memory cache only (refreshed at most every 3 hours)",
            NFL_REVIEWED,
            "General Terms (June 2018): registered use of the free tier under a fair-use "
            "policy, one application per key, attribution required. Needs the owner's free "
            "key in .env (KRT_FOOTBALL_DATA_API_KEY); without it soccer runs on price and "
            "news only. One endpoint (competition matches), at most every 3 hours per "
            "competition, under the 10-requests-a-minute limit. Team logos are never "
            "fetched (owned by the clubs). MLS isn't in the free tier.",
            (
                'You agree to include the following attribution to Football-Data in your app '
                'or website: "Football data provided by the Football-Data.org API".',
                "Developer credentials may not be stored in code repositories of open source "
                "projects.",
                "All graphics, including team logos and profile photos, are copyrighted by "
                "their legal owner.",
            ),
        ),
        DataSource(
            "openfootball",
            "openfootball football.json",
            "soccer",
            "fixtures and results (public domain)",
            "none",
            "https://github.com/openfootball/football.json",
            "structured_dataset_allowed",
            ("download_public_domain_json",),
            "openfootball (public domain, CC0)",
            "n/a",
            NFL_REVIEWED,
            "Public domain, but not connected: on review day (Nov 23) the 2026-27 files' "
            "latest results were from Sep 20, so season form would silently miss two months. "
            "Reconsider if it's kept current.",
            (
                "The football.json schema, data and scripts are dedicated to the public "
                "domain. Use as you please with no restrictions whatsoever.",
            ),
        ),
        DataSource(
            "football_data_uk",
            "Football-Data.co.uk",
            "soccer",
            "historical odds, scores, stats CSV",
            "none",
            "https://football-data.co.uk/contact.php",
            "blocked_pending_review",
            (),
            "Football-Data.co.uk",
            "n/a",
            REVIEWED,
            "Fair-use policy restricts derived products; needs explicit permission first.",
        ),
        DataSource(
            "the_odds_api",
            "The Odds API",
            "several",
            "sportsbook prices",
            "none",
            "https://the-odds-api.com/",
            "blocked_pending_review",
            (),
            "The Odds API",
            "n/a",
            REVIEWED,
            "Not reviewed. Sportsbook odds compare prices; they're not an independent "
            "probability estimate.",
        ),
        DataSource(
            "betting_pick_sites",
            "Pickswise, Boyd's Bets, Covers, PickDawgz, Sports Betting Dime, SBR",
            "several",
            "written picks and commentary",
            "app.investigate.search (via Brave metadata)",
            "https://www.covers.com/",
            "metadata_only",
            ("search_metadata",),
            "Publisher name and link; cited as opinion",
            "As Brave",
            REVIEWED,
            "Headlines and links only, always classed as analyst opinion. No full text "
            "without an explicit licence for automated processing.",
        ),
        DataSource(
            "guardian_open_platform",
            "The Guardian Open Platform",
            "mainly international sport",
            "full-text articles",
            "none",
            "https://www.theguardian.com/open-platform/terms-and-conditions",
            "blocked_pending_review",
            (),
            "The Guardian",
            "n/a",
            REVIEWED,
            "API access isn't AI-processing permission; its terms restrict AI and automated "
            "analysis without explicit permission. The terms page refused an automated read "
            "on review day, so it stays blocked.",
        ),
    ]
}


def disabled(settings: Any) -> set[str]:
    raw = getattr(settings, "research_disabled_sources", "") or ""
    return {x.strip() for x in raw.split(",") if x.strip()}


def allows(source_id: str, operation: str, settings: Any = None) -> bool:
    """True only if the reviewed terms allow this exact operation and the owner hasn't
    switched the source off. Unknown sources and operations are refused."""
    s = SOURCES.get(source_id)
    if s is None or operation not in s.allowed_operations:
        return False
    if s.rights_status in ("blocked_pending_review", "manual_user_input"):
        return False
    return not (settings is not None and source_id in disabled(settings))


def matrix(settings: Any = None) -> list[dict[str, Any]]:
    off = disabled(settings) if settings is not None else set()
    return [s.to_dict() | {"enabled": s.source_id not in off} for s in SOURCES.values()]
