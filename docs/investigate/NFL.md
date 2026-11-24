# NFL investigations: report

Follows Phase 3 of `trading_bot_evidence_expansion_fable.md`:
- licensed nflverse datasets, each checked on its own;
- starting QB, injuries, rest and weather, with timestamps;
- Kalshi's overtime and spread rules confirmed.

Built 2026-11-23. **No Brave request was made by this work.** Every Brave, GitHub and Open-Meteo test uses a mocked transport.

## Markets

| Kalshi series | Kind | Supported |
| --- | --- | --- |
| `KXNFLGAME` | game winner | yes |
| `KXNFLSPREAD` | winning margin over a line | yes |
| `KXNFLTOTAL` | combined points over a line | yes |
| `KXNFLTEAMTOTAL` | one team's points over a line | yes |
| `KXNFL1H…`, `…1Q…`, `KXNFL2QBTTS` | halves and quarters | no: "data is full-game only" |
| `KXNFLPASSYDS`, `RSHYDS`, `RECYDS`, `REC`, `PASSTDS`, `TD`, `PASSATT`, `PASSCOMP`, `PASSINT`, `RSHATT`, `RRYDS` (also `…PROT` and `…PRECISE`) | player stat props ("Josh Allen: 250+") | **yes (Nov 23)**; see *Player props* |
| `KXNFLFIRSTTD`, ladders, escalators, longest plays, D/ST touchdowns, kicking | other props | no: "this prop type isn't covered" |
| season, award and draft markets | no game date | no |

**Lines:** the line comes from Kalshi's `floor_strike`; the ticker number is the line plus 0.5 (`SPREAD-BUF8` means by over 7.5).

**Team codes:** Kalshi's codes match nflverse's except JAC→JAX and LAR→LA. All 32 are mapped.

## Settlement (read from Kalshi's public API, Nov 23)

| Market | Rule | How the app treats it |
| --- | --- | --- |
| Game winner | "If the game ends in a tie, the market will resolve to $0.50 for each team." Postponed over 48 hours resolves at a fair price. | Overtime counts. The tie rule is shown. |
| Spread | "wins by more than X points"; no secondary rules. | The official score includes overtime. A tie means NO. |
| Total, team total | "score more than X points"; no secondary rules. | Overtime points count. |

**Kickoff time:** Kalshi's `occurrence_datetime` is about three hours *after* kickoff. The app uses the nflverse schedule's Eastern-time kickoff, converted to UTC.

## Data sources and rights (`app/investigate/sources.py`, version 2026-11-23.1)

The nflverse-data repository is CC BY 4.0. Following the spec, one release's licence isn't assumed for another, so each file has its own entry and operation.

| Source id | File | Status | What's read |
| --- | --- | --- | --- |
| `nflverse_schedules` | `schedules/games.csv` | allowed | Kickoff, final scores, rest days, roof, stadium, listed QB. **The sportsbook columns** (moneylines, `spread_line`, `total_line`, odds) **are never read.** |
| `nflverse_team_stats` | `stats_team/stats_team_week_{season}.csv` | allowed | Passing and rushing EPA and plays, per team-game. These are nflverse's own aggregates. |
| `nflverse_injuries` | `injuries/injuries_{season}.csv` | allowed, **owner to confirm** | The NFL's weekly injury report as republished by nflverse: player, position, game status, practice status. |
| `nflverse_ftn` | FTN charting | blocked | Different licence, unconfirmed. Never downloaded. |
| `open_meteo` | forecast API | allowed | Kickoff-hour temperature, wind, gusts and precipitation chance. |

**Owner confirmations:**
1. **Schedules:** the schedule is maintained in Lee Sharpe's `nfldata` repository, which has no licence file. Only public game facts are used, and the release sits in the CC BY 4.0 repository.
2. **Injury report:** nflreadr says NFL data "belong to their respective owners, and are governed by their terms of use." Only status facts are used, and NFL.com is never fetched. If you'd rather not rely on it, set `KRT_RESEARCH_DISABLED_SOURCES=nflverse_injuries`. QB status then rests on the listing and news alone.

**Not used:**
- ESPN: not used for football (it stays basketball-only and legacy).
- NFL.com: never fetched.
- Depth charts: 79 MB, not needed.
- Play-by-play.

### Download rules
- **Paths:** only those three paths, enforced by an allow-list.
- **Redirects:** GitHub serves releases through one redirect to its asset host. Exactly one hop to `release-assets.githubusercontent.com` or `objects.githubusercontent.com` is followed; anything else is refused (tested).
- **Frequency and size:** at most once per 12 hours per season, with a 6 MB cap per file.
- **Failures:** if team stats or injuries fail, the investigation still runs on the schedule and says what's missing.

### Weather
- **When it's looked up:** one Open-Meteo request per game, cached an hour. Only when the game is:
  - at the home team's own open-air stadium (20 stadiums in a coordinate table);
  - within 7 days of kickoff.
- **Never looked up for:**
  - domes and closed roofs;
  - retractable roofs whose state is unknown (nflverse leaves `roof` blank: Dallas, Houston, Indianapolis, Atlanta, Arizona);
  - neutral and international sites. The schedule sometimes reuses a home id for a London game, so `location` must be "Home".
- **Timestamps:** each finding shows the forecast hour and the time it was retrieved.

## What a result shows

1. **Starting quarterbacks (always first; the model can't remove it).**
   - **Expected:** the schedule lists the QB (a projection), or a news headline or snippet names a candidate with a starting phrase. Candidates are the listed QB, this season's previous starters and QBs on the injury report.
   - **Unknown:** the listed QB is **Out or Doubtful** on this week's report, or nobody is listed. The season's starters are shown as options.
   - **Conflicting:** reports name a different starter from the listing, or two different starters. Syndicated copies count once.
   - **Never confirmed:** there's no official lineup source. The summary filter drops any model text calling a QB "confirmed".
2. **Points per game, before kickoff:**
   - for the game winner and spread, a rough margin, compared with the line for spreads;
   - for totals and team totals, a rough scoring average compared with the line.
   - No home-field or QB adjustment is made. Each is labelled "not a probability".
3. **The week's injury report:** Out and Doubtful players by name and position, and the questionable count.
   - **If the file doesn't have this week yet** (common: it lagged a week on Nov 23), it says so. Players are then shown as unknown, never healthy.
4. **EPA per play:** offense, and what each defense allows.
5. **Rest and venue:** rest days, stadium and roof, division game, the weather or why it wasn't checked.
6. **Sample caveat:** "N and M games played before this kickoff". The season form is point-in-time: games after this kickoff are excluded.

**No estimate or edge:** "No validated NFL probability model yet" is always among the reasons.

**Coverage line examples:**
- "2 factual datasets · 0 commentary links · starting QBs unconfirmed"
- "… · QB reports conflict"

**News (explicit runs only):** four queries, each counted against the one Brave cap:
1. "… NFL starting quarterback";
2. a preview;
3. "… NFL injury report";
4. a spread, total or prediction angle.

Results must be about football. This drops, for example, MLB "Giants" stories and NHL "Panthers" stories. NFL line ranges are used for the line check.

## Verified live (free sources only; Brave and the model off)

- **`krt research-smoke --live-nflverse`:** "nflverse 2026: 272 games (163 played), 32 teams, 324 team-week rows, 3481 injury rows (latest week 11), data as of 2026-11-24 05:23 UTC".
- **Deterministic investigations of 12 real catalog markets:**
  - games: GB@LAR, CHI@DET, PHI@DAL, KC@BUF;
  - market types: game winner, spread, total, team total.
  - **Results:**
    - all mapped exactly (lines, subjects, settlement text);
    - point-in-time form of 10 to 11 games;
    - listed QBs shown as projections;
    - the week-12 injury gap stated honestly;
    - dome and retractable-roof games skipped weather;
    - the open-air Buffalo game got a real Open-Meteo kickoff forecast;
    - no edge and no errors.
  - **`research-eval`:** unsupported claims 0, uncited 0.

## Tests

`backend/tests/test_nfl.py` has 19 tests:
- market kinds and unsupported reasons;
- settlement text;
- team codes and seasons;
- Eastern-to-UTC kickoff (EST and EDT);
- point-in-time form and EPA;
- QB states (listed, news, conflicting, syndicated copy, Out → unknown, unlisted);
- end-to-end for all four market types, checking:
  - weather and caching;
  - the sportsbook columns never surfacing;
  - one download per file;
- the missing injury week shown as unknown;
- the switches (injuries off, Open-Meteo off, schedule off);
- the adapter's allow-list, redirect refusal and partial failure;
- the weather limits;
- the news query plan and football filter;
- the synthesis never calling a QB confirmed;
- the per-dataset registry.

**Results:**
- **Backend:** 491 pass (472 before); ruff clean.
- **Frontend:** 142 pass (an NFL support and line test added); typecheck, build and bundle scan clean.

## Player props (added Nov 23)

**Data:** nflverse's weekly player stats, `stats_player/stats_player_week_{season}.csv`.
- It's nflverse's own CC BY 4.0 aggregate, with a separate registry entry (`nflverse_player_stats`).
- It's downloaded only when a prop is investigated, and cached 12 hours.

**Settlement** (read from Kalshi's rules, Nov 23):
- The player's official stats count.
- If he's active but never plays a live snap, the market settles at a fair price.
- Protected (`…PROT`) contracts also settle at a fair price if he plays in the first half but not after it, unless he already reached the line.
- Touchdown props count touchdowns he scores (rushing, receiving or returns), not ones he throws.

**Mapping:**
- **Player:** the name comes from the contract ("Josh Allen: 250+") and the team from the ticker code.
- **Name matches:** two players with the same name are resolved by team, or refused. Buffalo's QB and Jacksonville's LB, both named Josh Allen, are a real case (tested).
- **Line:** from `floor_strike`, so 250+ is over 249.5.

**What a result shows:**
1. **Player status, pinned first:**
   - this week's injury-report status, or "report not out yet";
   - for a quarterback prop, whether the schedule lists someone else as the starter;
   - the inactive/fair-price rule.
2. **Frequency:** how often he reached the line before this game, with his average and last five games.
   - A player has a row only in games with a recorded stat. Team games without one (inactive, or no catch or carry) are shown, for example "2 of 9 games with a stat line (2 of 10 team games…)".
   - The price lens counts those games as **misses**, the cautious reading.
3. **Opponent context:** what the opponent allows per game in the matching team stat, against the league average.

**Price lens:** the frequency appears as history, with an 80% Wilson range and a "small sample" note. **No conservative edge is ever computed** (no validated model).

**Verified live (Nov 23):**
- Jared Goff reached 250+ passing yards in 7 of 10 games, and Chicago allows 234 a game against a 234 league average.
- Davis Allen reached 20+ receiving yards in 2 of 9 games with a stat line (2 of 10 team games).
- Jordan Love's rushing prop was hit in 0 of 10 games.
- A D/ST touchdown market was refused.

**Tests:** `backend/tests/test_nfl_props.py` (7).

## Gaps

- **Lineups:** no official NFL lineup source, so "confirmed" is unreachable by design.
- **Season averages are coarse:**
  - no opponent adjustment;
  - no home-field term;
  - no recent-form window.
- **Not checked:** travel, coaching changes and late scratches.
- **Weather:** retractable-roof games aren't checked (open or closed isn't published in the data).
- **Not covered:** halves and quarters; first touchdown, ladders, escalators, longest plays, D/ST and kicking props.
