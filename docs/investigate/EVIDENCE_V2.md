# Research Intelligence v2: report

Follows `trading_bot_evidence_expansion_fable.md`, `PHASES_C_TO_F.md` and `COLLEGE.md`.
Built 2026-11-21.

**No Brave request was made by this work.** Every Brave test uses a mocked transport. The
real ledger shows 12 requests, all from the app being used before this work started:
- 8 Investigate, on Nov 21 between 01:08 and 02:24 UTC;
- 3 AI-review headlines, at 02:12 UTC;
- 1 "Headlines here", at 15:56 UTC.

None came from tests or scripts.

## Supported leagues

| League | Markets | Structured evidence | Edge shown? |
| --- | --- | --- | --- |
| NBA, WNBA | winner, spread, totals, player props | ESPN box scores, injury report | Only with 15+ games, a fresh quote and a normal lineup |
| NCAA men's and women's | winner, spread, totals | ESPN box scores (no injury report exists) | Never (lineup unknown) |
| **NHL (new)** | winner, puck line, game total, team total | MoneyPuck season data | Never (no validated model) |
| **NFL (added Nov 23)** | winner, spread, game total, team total | nflverse schedule, team stats, injury report; Open-Meteo weather | Never (no validated model); see `NFL.md` |
| **Soccer (added Nov 23)** | winner (incl. Tie), spread, totals, both teams to score | football-data.org results (keyed; not MLS) | Never (no validated model); see `SOCCER.md` |

**NHL is not supported for:**
- periods (`1P`/`2P`/`3P`);
- overtime and first-goal markets;
- first-10-minutes markets;
- player props;
- season markets.

Each gets a clear reason.

## Phase 1: one Brave budget for the whole app

- **Caps:**
  - 60 a day and 800 a month apply to the **total** across every caller: Investigate, "Headlines here" and the AI reviews' headlines.
  - The purpose tag only breaks usage down; no caller has a budget of its own.
- **Defaults are also maximums:** daily ≤ 60, monthly ≤ 800, per investigation ≤ 5.
  - 800 requests is about $4 at Brave's published $5 per 1,000, leaving roughly $1 of a $5 monthly credit as a reserve.
  - The caps can be lowered in `.env`; raising them needs a code change.
- **Atomic check:** each network attempt (retries included) is checked against the day and month totals and recorded inside one SQLite `BEGIN IMMEDIATE` transaction, plus a process lock.
  - Tested: 60 threads across three purposes against a cap of 20 got exactly 20.
- **No retries:** retries are off by default (`max_retries=0`), so a 429 or an outage isn't retried.
  - An exhausted budget stops the request before it's sent.
  - The AI reviews then carry on without headlines.
- **"Headlines here":** now a POST with the `X-KRT-Request` header, so a link or page on another site can't spend it.
  - Repeat clicks are served from a 30-minute in-memory cache, which costs nothing.
- **Ledger contents:** time, purpose and a SHA-256 of the query only. Never the query text and never any Brave response (tested).
- **Drawer display:** "Brave requests: N / 800 this month", with today's count and a per-feature breakdown on expand. No "$ remaining" figure is ever shown.
- **Retention unchanged:** snippets are never stored, and article headlines and links are deleted from saved investigations after the cache window.
- **Not verified:** that your Brave plan prices News Search at $5 per 1,000. Check the dashboard.

## Phase 2: source rights matrix (`app/investigate/sources.py`)

Reviewed 2026-11-21 by reading each source's published terms. Short quotes are kept in the registry.

| Source | Status | Allowed operations | Why |
| --- | --- | --- | --- |
| Kalshi public API | structured_dataset_allowed | read markets, rules | The exchange's own documented API |
| Brave News Search | metadata_only | search metadata, transient snippet | Brave allows transient storage only |
| ESPN site JSON | **legacy_unreviewed** | basketball box scores and injuries | Used before this registry; no licence found; **not used for hockey or any new sport** |
| MoneyPuck season CSVs | structured_dataset_allowed | download the two listed season CSVs | "free to use for non-commercial purposes"; credit required; other pages need approval |
| NHL api-web endpoints | blocked_pending_review | — | No published terms; NHL.com terms bar "unauthorized automated means" |
| PuckAPI | blocked_pending_review | — | Needs a key and a terms review |
| Open-Meteo | structured_dataset_allowed | non-commercial forecast lookup | CC BY 4.0, under 10,000 calls a day; connected for open-air NFL stadiums (Nov 23) |
| nflverse (per dataset, Nov 23) | schedules, team stats, injuries allowed; FTN blocked | one release file each | See `NFL.md`: one release's licence isn't assumed for another; sportsbook columns never read |
| StatsBomb Open Data | blocked_pending_review | — | LICENSE.pdf couldn't be read |
| NCAA API wrapper | blocked_pending_review | — | A code licence isn't a data licence |
| Sports Insights RSS, CBS RSS | metadata_only | — | Feed terms not reviewed; not connected |
| Football-Data.co.uk, The Odds API | blocked_pending_review | — | Permission needed or not reviewed |
| football-data.org (Nov 23) | structured_dataset_allowed | competition fixtures and results (keyed) | Registered free tier, fair use, attribution; see `SOCCER.md` |
| openfootball (Nov 23) | allowed (CC0), not connected | — | Public domain but stale (last results Sep 20) |
| Betting pick sites | metadata_only | via Brave metadata | Cited as opinion; no full text |
| Guardian Open Platform | blocked_pending_review | — | Its terms restrict AI processing; the page refused an automated read |

- **Full text:** no source is `licensed_full_text`. Nothing fetches or stores an article.
- **Enforcement:** adapters call `sources.allows(id, operation)`. Unknown sources or operations are refused.
- **Owner switch:** `KRT_RESEARCH_DISABLED_SOURCES` turns a source off; it can never grant rights.
- **Visibility:** `GET /api/research/sources` returns the matrix.

**Enabling more needs:**
- for the NHL endpoints, written NHL permission or a licensed feed;
- for StatsBomb, reading the LICENSE.pdf;
- for nflverse FTN, that dataset's own licence;
- for any publisher's full text, a licence covering automated processing and retention.

**Owner to confirm:** that personal betting research counts as MoneyPuck's "non-commercial" use. I read it that way, since the data isn't sold or republished.

**ESPN:** it's labelled honestly as unreviewed. You can turn it off with `KRT_SPORTS_EVIDENCE_ENABLED=false`, but that also turns off the basketball checks.

## Phase 3: NHL (`app/investigate/nhl.py`, `app/sportsdata/moneypuck.py`)

### Market mapping
Exact ticker, side, team and line. The line comes from Kalshi's `floor_strike`; `TOTAL-6` means over 5.5.

Settlement, from Kalshi's full rules text (read from the public API):

| Market | How it settles |
| --- | --- |
| Game winner | The official final result: overtime and shootout count. Never treated as a 60-minute bet. |
| Puck line | The official result. The rule doesn't mention shootouts; the NHL's official score credits the shootout winner one goal. Shown as a caveat. |
| Game total | Overtime goals count; a shootout counts as one goal for the winner. |
| Team total | Kalshi doesn't say how a shootout is scored for one team's total, so it's flagged as uncertain. |

### Starting goalie
- **States:** confirmed, expected, unknown, conflicting or not_applicable.
- **Unknown when nothing names a starter.** Season options are listed, for example "Levi 12 GP, Jarry 10 GP".
- **Expected (reported)** when a news headline or snippet names one of the team's goalies with a starting phrase.
- **Conflicting** when two reports name different goalies. Syndicated copies count once.
- **Never confirmed:** no official lineup source is connected, so even a headline saying "confirmed" gives *expected*.
- **Position:** the goalie finding is always first. The local model can't remove it or call anyone confirmed.

### Stats (MoneyPuck, credited "Data: MoneyPuck.com")
- 5-on-5 expected-goals share and goals for/against per game.
- **Puck line:** a rough season margin compared with the line. Being the better team doesn't mean winning by 2 or more.
- **Totals:** a rough combined average compared with the line, labelled a sanity check, not a probability.
- **Goalies:** the most-used goalie's save % and goals saved above expected.

### No estimate or edge
"No validated NHL probability model yet" is always listed as a reason.

### Time validity
If MoneyPuck updated after the game started, a finding says the figures may include it.

### Downloads
- Only `/moneypuck/playerData/seasonSummary/{year}/regular/{teams|goalies}.csv`, enforced by an allow-list.
- At most once per 12 hours (the data updates nightly). No redirects followed; 3 MB size cap.

### News
Four queries:
- "… NHL starting goalie confirmed";
- a preview;
- an injury update;
- a total, puck-line or prediction angle.

Results must be about hockey. This drops, for example, MLB "Rangers" stories and NFL "Jets" stories. Hockey-sized line ranges apply.

### Not checked (shown as gaps)
- rest and travel;
- injuries (no permitted NHL schedule or injury source);
- who starts in goal, beyond news reports.

## Phase 4: evidence streams and synthesis

- **Three evidence streams:**
  - **Structured facts:** K1 Kalshi, E1/E2 ESPN, M1 MoneyPuck.
  - **Published opinion:** N\* sources, metadata and snippets only.
  - **User excerpts (built Nov 23):** see *User-provided excerpts* below.
- **Model limits:**
  - The model is told it only sees headlines and snippets.
  - Any finding or takeaway implying it read an article ("according to the article", "full article") is dropped.
  - For hockey, any text calling a goalie "confirmed" is dropped. The deterministic takeaway is used instead.
- **Model's role:** it compares news against the structured facts, and has no tools, no trading and no probability adjustment.
- **Coverage line** under the takeaway, for example "1 factual dataset · 3 commentary links · goalie status unconfirmed".
  - Basketball shows "injury report checked" or "lineup unknown (no injury report)".
  - It's recounted when news expires.
- **Layout unchanged:** two sentences, up to three findings, price lens, one open question, full research collapsed.

## User-provided excerpts (Phase 4, stream 3; built Nov 23)

**What it is:** a paste box in the drawer, under the result ("Add an excerpt you've read"). You give:
- the text (20 to 4,000 characters);
- a source name;
- optionally a link and a published date.

**Rules (`app/investigate/excerpts.py`, source `user_excerpt`, status `manual_user_input`):**
- **Local only:** never fetched and never searched.
  - The link is stored for you and **never opened by the app** (tested: any real HTTP request fails the tests).
  - Adding or removing an excerpt spends no Brave request and makes no data download.
- **Always unverified:** each excerpt is shown as "user-provided, unverified" until another source agrees.
  - Each one gets a finding that never quotes it back.
  - A local-model claim that rests only on excerpts (`U1`, `U2`…) is always marked unverified.
  - A claim that also cites app data or news is treated as corroborated.
- **Deterministic checks**, the same rules as news:
  - doesn't read like this sport;
  - mentions a different line;
  - dated after the game;
  - dated well before the game (maybe an earlier meeting).
- **Local model, if configured:** it re-summarises with the excerpt text (up to 1,500 characters).
  - News snippets aren't stored, so news counts as headlines only in that re-summary, and the method says so.
  - The prompt says excerpts are data, to be quoted sparingly and never presented as fact.
  - If the model fails, the app's own summary stays.
- **Clean rebuilds:** the result keeps a snapshot of its pre-excerpt summary and details. Every add or remove rebuilds from it, so model claims don't pile up, and removing the last excerpt restores the original exactly (tested).
- **Retention:** an excerpt is your own local note, so it isn't on Brave's clock.
  - It stays until you remove it, and carries over when you refresh the research.
  - The news purge still removes everything written from news, including from the snapshot (tested), and keeps the excerpts.
- **Limits:**
  - at most 5 per investigation;
  - both endpoints are POSTs with the CSRF header;
  - links must be `http(s)`;
  - control characters are stripped.
- **Owner switch:** `KRT_RESEARCH_DISABLED_SOURCES=user_excerpt` turns the paste box's endpoint off.
- **Coverage line:** for example "1 factual dataset · 2 commentary links · 1 excerpt you pasted · …".
- **Endpoints:**
  - `POST /api/research/investigations/{id}/excerpts`;
  - `POST /api/research/investigations/{id}/excerpts/{U1..}/remove`.
- **Tests:** `backend/tests/test_excerpts.py` (8) and 2 drawer tests.

## Phase 5: evaluation (`app/investigate/evaluate.py`)

- **`krt research-eval`:** offline report over saved investigations. It covers:
  - mapping accuracy (side, kind, line, statement);
  - news published after the game started;
  - stats updated after the game started;
  - unverified and uncited claim rates;
  - duplicates and conflicts;
  - how often structured data adds numbers no headline has;
  - missing evidence by league;
  - errors split into permission / data-or-source / model.
- **Calibration** is reported as "not applicable" until a validated numeric model exists.
- **`krt research-smoke --live-moneypuck`:** downloads MoneyPuck's two files once (free, never Brave). Without the flag it prints what it would do and does nothing (tested).

## Verified live (free sources only; Brave and the model off)

- **`research-smoke --live-moneypuck`:** "MoneyPuck 2026: 32 teams, 77 goalies, data as of 2026-11-21 11:41 UTC".
- **Team codes:** all 32 Kalshi NHL codes map. Four differ: LA→LAK, NJ→NJD, SJ→SJS, TB→TBL.
- **Deterministic investigations** of 8 real markets from Edmonton–Carolina (Nov 21): winner both sides, puck line 1.5 and 2.5, totals 1.5 and 2.5, team totals.
  - All showed goalies unknown first, credited MoneyPuck numbers and no edge, with no errors.
  - Evaluation rates: unsupported 0, uncited 0, structured adds 1.0.
- **A puck-line flaw found and fixed:** the first version leaned on overall team strength. It now compares a goal margin with the line.

## Tests (actual results)

- **Backend:** 472 pass (445 before), 0 failed; ruff clean. New files:
  - `test_brave_budget.py`: shared cap across purposes, the "Headlines here" POST/CSRF/cache/429/exhausted paths, AI headlines stopping at the cap, no responses stored.
  - `test_nhl.py`: mapping, goalie states, end to end, switch, leakage, adapter allow-list and cache, news filter, synthesis safety, registry.
  - `test_research_eval.py`.
- **Updated:**
  - write-route lists in `test_api.py` and `test_signals.py` (the news POST);
  - the usage shape in `test_investigate.py`;
  - NHL support in `test_investigate.py::test_supported_checks`.
- **Frontend:** 141 pass, typecheck clean, build OK, bundle secret scan clean.
  - New: NHL support and lines, and the usage line with breakdown and no "$ remaining".

## Known gaps and next steps

- **NFL and soccer:** connected on Nov 23 (`NFL.md`, `SOCCER.md`). StatsBomb still needs its licence read.
- **User-provided excerpts (Phase 4 stream 3):** built Nov 23 (see above).
- **Background job queue for long model runs (optional Phase 6):** not built.
- **No official NHL lineup source:** "confirmed" is unreachable by design until one is licensed.
- **NHL injuries, rest and travel:** not checked.
- **NHL player props:** not supported.
- **Season-level stats are coarse:** there's no recent-form window, because MoneyPuck's game-by-game files weren't wired in, to keep downloads to the two listed files.
