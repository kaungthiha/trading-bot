# Investigate this pick: college basketball (men's and women's) and WNBA

Follows `PHASES_C_TO_F.md`, which limited investigation to the NBA. This adds:
- men's college basketball (`KXNCAAMB…`);
- women's college basketball (`KXNCAAWB…`);
- the WNBA (`KXWNBA…`), which box-score evidence already covered.

**Scope:** game winner, spread and game total. Halves (`1H…`), rankings, coach and stat-leader
markets are not supported. No Brave search was made while building or verifying this.

## Why college needed its own rules
| Difference | What the app does |
| --- | --- |
| 360+ schools; Kalshi codes often differ from ESPN's (`TARL`/`TAR`, `MIZZ`/`MIZ`, `CHAT`/`UTC`) | Teams are matched by the **school name** Kalshi shows (`Tarleton St.`), normalized on both sides ("St." at the end = State, "&" = and). The code only breaks ties. A small table covers 8 spelling differences (`University at Albany` → `UAlbany`, `LIU` → `Long Island University`…). No confident match → "Couldn't match the team on ESPN", never a guess. |
| ESPN publishes **no college injury report** | The injury feed isn't requested. The lineup is treated as **unknown, never as normal**, so **no conservative edge is ever shown** for college. The first finding and first gap say so, and the local-model summary can't remove it. On the Games page, the injury strip says "No injury report is published for this league" instead of "No injuries listed", which would read as healthy. |
| Opponent strength varies enormously (non-conference schedules) | The takeaway says "Past games (against mixed opponents)…", and the history finding says it "says little about tonight's matchup". |
| Same school names for football and both basketball programs | News queries name the sport ("… basketball preview", "… women's basketball preview"). Results must mention basketball, and men's and women's articles are kept apart. Football and the other program are dropped as `other_sport`. |
| Different scoring | Line matching uses college ranges: men's totals 100–200, women's 90–190, spreads up to 55/60. A 135.5 total is "exact" for college but outside the NBA range. |
| 360+ teams in ESPN's list | The teams request asks for `limit=1000`, and team ids up to 6 digits are allowed by the ESPN path allowlist (`Long Island University` is 112358). |

## Verified against live data (ESPN only, free)
- **Team matching** across every college game in the local catalog: men's 340/346, women's
  344/344. The 6 unmatched are non-Division I opponents (Averett, Bloomfield, Ecclesia,
  Indiana-South Bend, Worcester St., West Virginia Tech), which ESPN doesn't list, and they
  correctly fail closed. Every match whose code differs from ESPN's abbreviation was checked
  by eye.
- **Schedules:** current and previous seasons load with final scores (for example, Kansas
  men: 5 this season and 33 last; UConn women: 5 and 39).
- **Deterministic investigations** of real `NCAAMBGAME`, `NCAAMBSPREAD`, `NCAAWBGAME` and
  `NCAAWBTOTAL` markets: history found, no edge, the lineup-unknown finding first, and no
  errors.

## Policy and cache
- `POLICY_VERSION` is now `v4`, and the publisher registry is `2026-11-20.2` (adds NCAA.com,
  WNBA.com, FOX Sports, Sports Illustrated; full text is still not permitted for any).
- Both changes invalidate cached investigations.

## Tests
- `backend/tests/test_college.py` (18 tests):
  - name matching, fail-closed cases and Saint/State;
  - market kinds, including halves;
  - support checks;
  - end-to-end men's and women's runs: no edge, injury feed never requested, the injury strip
    says "not supported", `limit=1000`;
  - sport-named queries and sport/program filtering;
  - college line ranges;
  - the summary keeps the lineup-unknown finding.
- `Investigate.test.tsx`: college and WNBA support, halves and rankings excluded.
- `Games.test.tsx`: a league with no injury report says so instead of "No injuries listed".
- Backend 441 and frontend 139 tests pass; the build and bundle scan are clean.

## Known limits
- **Early season:** teams have 2–7 games in November, under the 15 needed even for a
  pro-league edge. College results will read "insufficient" for weeks, and for college an
  edge is never shown anyway.
- **Player props:** Kalshi lists few for college. They go through the same path (ESPN player
  search for that league) but aren't specifically tested.
- **Neutral-site and tournament games** are treated like any other game.
- **New Division I schools,** or Kalshi renaming a school, may need a line in `COLLEGE_NAMES`
  (`backend/app/sportsdata/espn.py`). An unmatched team shows a clear "couldn't match"
  message.
