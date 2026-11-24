# Soccer investigations: report

Follows Phase 3 of `trading_bot_evidence_expansion_fable.md` ("soccer later"). Built 2026-11-23.

**No Brave or football-data.org request was made by this work.** Tests use mocked transports, and no football-data.org key exists yet.

## Leagues and markets

| League (Kalshi prefix) | Results source |
| --- | --- |
| Premier League (`KXEPL`), La Liga (`KXLALIGA`), Bundesliga (`KXBUNDESLIGA`), Serie A (`KXSERIEA`), Ligue 1 (`KXLIGUE1`), Champions League (`KXUCL`) | football-data.org free tier (**needs your key**) |
| MLS (`KXMLS`) | none permitted yet: price, rules and news only |

**Supported:**
- `GAME`: three-way, with team A, team B and a separate **Tie** contract;
- `SPREAD`: wins by more than a line;
- `TOTAL`;
- `TEAMTOTAL` (Champions League);
- `BTTS`, a new market kind, "Both teams to score".

**Refused, with a reason:**
- halves (`1H…`, `2H…`);
- corners (`CORNERS`, `TCORNERS`);
- correct score;
- first team to score;
- second divisions (`KXLALIGA2…`, `KXBUNDESLIGA2…`);
- season markets.

**Lines:** the ticker number is the line plus 0.5 (`TOTAL-3` means over 2.5; `SPREAD-MCI2` means by more than 1.5).

## Settlement (read from Kalshi's public API, Nov 23)

Every market:
- settles **"after 90 minutes plus stoppage time (does not include extra time or penalties)"**;
- counts own goals for the team awarded the goal (stated for BTTS and team totals).

**Game winner:** "If the game ends in a tie, the market called 'Tie' resolves to Yes." A match cancelled or moved more than 48 hours resolves at a fair price.

**Spreads:** a draw or a narrower win is NO.

**Results are read as 90-minute scores to match:**
- a match with football-data's `duration` other than `REGULAR` uses its `regularTime` score;
- if there's no regular-time score, the match is **left out** and counted in a note. The extra-time or shoot-out total is never used (tested).

## Data source and rights

**Previously blocked, and still blocked:**
- StatsBomb Open Data: licence unread, and historical only;
- Football-Data.co.uk: its fair-use policy needs permission.

| Source | Status | Notes |
| --- | --- | --- |
| **football-data.org** (`football_data_org`) | allowed, **keyed** | General Terms (June 2018): registered free tier, fair use, one application per key, **attribution "Football data provided by the Football-Data.org API"** (shown with every number). |
| openfootball `football.json` | allowed (CC0), **not connected** | Public domain, but stale on review day: the 2026-27 files' last results were Sep 20, so season form would silently miss two months. |

**football-data.org obligations, and how the app meets them:**
- **Key privacy:** "Developer credentials may not be stored in code repositories." The key is a `SecretStr` read from `.env` only:
  - `.env` is git-ignored, and `.env.example` has an empty `KRT_FOOTBALL_DATA_API_KEY=`;
  - it's sent only as the `X-Auth-Token` header;
  - it never appears in a result, the sources matrix or a URL (tested).
- **Logos:** team logos are owned by the clubs and are never fetched.
- **Fair use:** one endpoint, `/v4/competitions/{PL|PD|BL1|SA|FL1|CL}/matches?season=Y`, allow-listed.
  - Cached 3 hours per competition-season, so one request serves every match in that league.
  - A local throttle refuses a 10th request inside a minute (the free plan allows 10), rather than queueing it.
  - No redirects are followed.

**Coverage gap:** the free tier excludes MLS, so MLS runs on price, rules and news only.

**ESPN** isn't used for soccer.

## Matching Kalshi teams to football-data clubs

Kalshi uses short and sometimes odd names: "Bilbao", "Atletico", "Inter", "Eindhoven", "Mögladbach" (stored as "M´gladbach"), "FC Cologne".

**How a match is decided:**
1. **Date window:** only fixtures within a day of the ticker's date are considered.
2. **Word scoring:** exact words score 1 and 4+ letter prefixes 0.75, after normalising accents and dropping club suffixes (FC, CF, AC…). The score is weighted by how much of the official name is explained, so "Barcelona" is FC Barcelona, not RCD Espanyol de Barcelona, and "Paris FC" isn't Paris Saint-Germain.
3. **Aliases:** a small table covers names that share no word with the official name (Bilbao→Athletic, PSG, Mönchengladbach, Cologne→Köln and others).
4. **Code fallback:** the three-letter code alone gives 0.9.
5. **No guessing:** both teams must score at least 0.5, or the result says the match couldn't be matched.

**Verified:** all **96 distinct Kalshi team names** in the catalog, across the five domestic leagues, resolve to the right club. This used openfootball's official club names, without the code fallback.

## What a result shows

1. **Team news, always first and pinned:** no lineup or injury source is connected, so who plays is unknown. It's never assumed normal.
2. **Main figure for the market,** from 90-minute results **before this kickoff** (later matches excluded):
   - **winner:** each team's W-D-L and goals per match, with a rough goal margin. A win must also beat the draw, and the result says so.
   - **Tie:** each team's draw count.
   - **spread:** how often the team won by more than the line, how often the opponent lost by more than it, and a rough margin compared with the line.
   - **total:** each team's share of matches with more than the line, and a rough combined average.
   - **team total:** how often the team scored more than the line, and how often the opponent conceded more.
   - **both teams to score:** each team's both-scored rate, failures to score and clean sheets.
3. **Venue and recent form:** the home team's home record, the away team's away record, and each team's last five results.
4. **Sample caveat:**
   - the number of matches counted;
   - that other competitions, opponent strength and fixture congestion aren't counted;
   - matches left out for lacking a 90-minute score.

**No estimate or edge:** "No validated soccer probability model yet" is always listed. Every figure is labelled context, not a probability.

**Coverage line:** for example "1 factual dataset · 0 commentary links · team news unknown (no lineup source)".

**News (explicit runs only):** three queries, all within the one Brave cap:
1. team news;
2. a preview;
3. a total, both-teams-to-score, handicap or prediction angle.

Results must be about soccer and not about American football. This drops, for example, Cowboys stories for Dallas and "Arsenal Firearms" stories.

## Without a key (today)

A soccer investigation still runs:
- exact mapping, settlement rules and the price lens;
- news, if Brave is set up.

It says: "Soccer results aren't checked: set KRT_FOOTBALL_DATA_API_KEY (free football-data.org registration) to add them." This was verified live on real EPL, Champions League, La Liga and MLS markets. Corners were refused.

**To add the key:**
1. Register at https://www.football-data.org/client/register.
2. Put the key in `.env` as `KRT_FOOTBALL_DATA_API_KEY=...`.
3. Run `krt research-smoke --live-football-data`. It sends one request and summarises the Premier League season.
4. Restart the app.

## Tests

`backend/tests/test_soccer.py` has 20 tests:
- market kinds and refusal reasons;
- 90-minute settlement in every rule;
- 90-minute score extraction (extra time uses regular time; shoot-outs without one are excluded);
- team-name resolution, including Kalshi's quirks;
- point-in-time form and the home/away split;
- end-to-end for winner, Tie, total, both teams to score and a NO on a spread, checking that:
  - one request is made, with the key only in its header;
  - the key never appears in results;
- no key means no request;
- the switch;
- refused corners;
- a refused key reported;
- the adapter's allow-list, cache and throttle;
- MLS without data;
- the news query plan and filter;
- the pinned team-news finding;
- the registry entries and secret handling.

**Results:**
- **Backend:** 511 pass (491 before); ruff clean.
- **Frontend:** 143 pass (a soccer support test added), plus typecheck, build and bundle scan.

The NHL and NFL builders now share the price lens and Kalshi source with soccer (`app/investigate/common.py`). Their tests are unchanged and pass.

## Gaps

- **Lineups and injuries:** no source, so team news is always unknown.
- **MLS:** no permitted results source.
- **Form is coarse:**
  - competition-only (no domestic cups or Europe for league games);
  - no opponent adjustment;
  - no expected-goals data;
  - small Champions League samples.
- **Not checked:** weather, rest and travel.
- **Not covered:** half, corner, correct-score and first-to-score markets.
