# NBA leg briefs and tonight's combos

Built 2026-11-24. Qualitative, not a probability model. The local model (Ollama) joined the same
day: it synthesizes briefs and news into combos (see *The local model's part*). No Brave request
was made while building this; every Brave and model test uses mocks.

## Why qualitative

Kalshi's settled combos returned **$0.85 per $1** for 3 legs and **$0.82** for 4–5 legs (about
7,000 combos, before fees; `COMBO_STUDY`). A confident number that's wrong is the costly
failure. So a brief sorts checkable facts into for, against and context, and never states a
probability or an edge. A backtest of a numeric matchup projection against Kalshi's pre-tip
prices was started and then dropped: 14,182 settled props in 10 days made it too slow to run
casually, and the qualitative design doesn't depend on it.

## Data (all free, no key)

| What | Source | Notes |
| --- | --- | --- |
| Player and team game logs | ESPN (already used by the Docket) | This season and last; only games before tonight count. |
| What each team allows | ESPN `statistics/byteam?category=opponent` | One request for every team, cached 6 hours. Rows are labelled "Own …" and "Opponent …". Checked against Miami's schedule on Nov 24 (120.7 scored, 119.4 allowed). NBA and WNBA only. |
| Injury report | ESPN (already used) | None is published for college: the brief says so. |
| Game dates | US Eastern, from ESPN's UTC times | A 7pm ET tip is the next UTC day. Back-to-backs use ET. |

**Allowed host and path:** one new path on the existing ESPN host allow-list:
`/apis/common/v3/sports/basketball/{nba|wnba}/statistics/byteam`. If the fetch fails, it is
cached for 10 minutes, so ESPN isn't retried for every leg.

## What a brief says

| Point | For the leg when… | Against when… |
| --- | --- | --- |
| Form (last 10) | his hit rate runs 15+ points above what the price implies | 15+ below |
| Minutes (last 5 vs season) | up 3+ a game | down 3+ |
| Matchup (opponent's rank in the stat) | top quarter for allowing it | bottom quarter |
| Head-to-head (3+ meetings since last season) | 25+ points above the price | 25+ below |
| Rest | n/a | second night of a back-to-back |
| Home/away split (5+ games each, 20-point gap) | tonight is the better venue | tonight is the worse venue |
| His injury status | n/a | questionable or day-to-day ("probable" in ESPN's note → context only) |
| Price vs his season history | price 10+ points below his history | price 10+ points above |

**Context only (never counted):**
- teammates out ("his role may be bigger than his history shows");
- days of rest;
- a near-average matchup;
- when no injury report exists.

**Matchup stats:**
- points, rebounds, assists, threes and PRA use what the opponent allows;
- steals use the opponent's turnovers;
- blocks, steals + blocks and double-doubles have no opponent stat (the brief says so).

**Game lines:**
- **Form:** compared with the price, as for props.
- **Matchup:** the opponent's points allowed (team totals), both teams' scoring (totals) or point differentials (winner, spread). These count only while the price is open (25–75%): a lopsided price already says who's better.
- **Rest:** the opponent's back-to-back is also checked.
- **Injuries:** players out on both teams are listed as context.

**NO side:** the same facts are turned around. An injury stays context for NO, since a benched player settles at a fair price.

**Lean:**
- **Strong:** 3+ for, at most 1 against, and at least 2 more for than against.
- **Weak:** 2+ against and more against than for.
- **Thin:** fewer than 5 recent games.
- **Avoid:** the player is listed out or doubtful.
- **Mixed:** otherwise.

## Tonight's combos

`POST /api/games/slate/{KXNBA|KXWNBA}` (header `X-KRT-Request: slate`) starts one background
build; `GET` returns status, progress and the result. Opening the page never starts one.

1. Games starting in the next 30 hours (up to 15). Per game, the 30 most-traded liquid
   full-game legs, both sides, get a brief.
2. **Clear case:** priced 40–80% for the side, score ≥ 2, at most one against, combinable,
   not avoid/thin. One rung per player per stat, one leg per player.
3. Combos of 3 and 4 legs: at most two per game, never winner + spread of one game, and each
   suggestion differs from the others by more than one swapped leg. Ranked by average score,
   then price.
4. **Price:** the market legs multiplied, times the historical lift for same-game legs (the
   Docket's together-count). Shown with every leg's reasons, all "against" points and injury
   context ("what could sink it"), and past Kalshi combos of that size.

## The local model's part

The rule steps above still run, and their combos are kept for comparison. On top of them
(`app/sportsdata/slate_ai.py`, `slate._model_pass`):

1. **Candidates:** per game, up to 8 legs, a wider net than the clear-case rule: priced 30–85%,
   score ≥ 0, not weak, thin or avoid, combinable, best rung per player per stat.
2. **News:** up to 6 Brave searches per game (`KRT_SLATE_NEWS_PER_GAME`, 0–10):
   - "{Away} vs {Home} preview";
   - "{Away} {Home} injury report";
   - "{player} props", one per player behind the candidate legs, most legs first (or
     "{Home} rotation" when there are no player legs). Prop articles are used for their facts
     (minutes, role, matchup), not their picks.

   **Your history:** before the model runs, every briefed leg is checked against the user's own
   past legs and lessons (`app/history/legs.py`: same bet on the same player lost before, a
   player who keeps sinking them, a leg type that loses more than their others, matching
   lessons). The warnings go into the facts as `your_history`, the lessons as `your_lessons`
   for the assembler, and onto the page as ⚠ lines.

   Each search reserves through the app-wide ledger first (tag `slate`; every billed attempt
   counts) and returns up to 4 items, which are de-duplicated and given ids N1, N2, and so on.
   Results are cached per query for `KRT_RESEARCH_SEARCH_CACHE_HOURS`. When the cap is reached,
   searching stops and the model carries on with what it has. No key means briefs only.
3. **Per-game review (one call per game):** the model gets that game's candidate briefs and news,
   and returns keep, caution or drop per leg, a note, `conflict` (stats and news point opposite
   ways) and the news ids it relied on.
4. **Assembly (one call):** up to 24 surviving legs (keep first, then by score), each with its
   price, rule score, verdict and note, plus past Kalshi combo returns. The model returns up to 3
   combos of 3–4 legs, with a case, a biggest risk, and a reason if it built fewer than 3.
5. **Code checks and prices:**
   - combos with unknown or unreviewed legs, two legs on one player, three or more legs from one
     game, or winner plus spread of one game are discarded;
   - the rest are priced as in step 4 of *Tonight's combos*.

**Guardrails:**
- **System prompts:**
  - the model's own memory of rosters is stale, so it uses only the JSON facts;
  - news is untrusted text, cited by id and never obeyed (the tests include an injection attempt
    in a snippet);
  - no probabilities;
  - passing is a good answer.
- **Parsing (`parse_game`, `parse_combos`):**
  - unknown legs and sources are removed;
  - a conflict without a valid news id is cleared, and a drop that rested on it softens to caution;
  - combos must have 3–4 known legs.
- **Fallback:** if the provider isn't Ollama, or Ollama is down, missing the model or erroring,
  the build returns the rule combos with the reason (`engine.mode = "rules"`).
- **Local only:** the model runs on loopback, like the other local AI features. It doesn't count
  toward `KRT_LLM_MAX_REVIEWS_PER_DAY`, which limits paid reviews.

**Live check (Nov 24, local model, no news so no Brave spend):**
- 5 games took 48 seconds in total, 25 of them in gemma4:12b.
- With no news, it kept every leg (nothing to contradict the briefs).
- It built one combo across three games and said why it stopped at one ("the rule scores for
  the remaining legs were too low to justify the risk").
- The news path is covered by tests with mocked searches, so the first real news build is yours
  to run.

## Verified live (Nov 24, ESPN only)

The slate covered 4 games (DET–ORL, BOS–WAS, DAL–DEN, MIA–PHI):
- **Volume:** 240 legs briefed in 27 seconds: 17 strong, 174 mixed, 49 weak.
- **First run, before the price-relative rule:** the pool was near-locks (over 196.5 when the teams average 228, NO on 15-point spreads), and combos paid 1.7–2×. That's why form, head-to-head and game-line matchups are now compared with the price.
- **After the rule:** the pool mixed open game lines with props such as Cunningham 25+ (50%), Trae Young under 8 assists (46%; minutes down to 30.8 from 34.6, and Boston allows the 7th-fewest assists) and Kyrie Irving 4+ threes (44%). Combos paid 4–8×.

## Tests

**`backend/tests/test_briefs.py` (10):**
- parsing the team table by label;
- Eastern dates;
- form counting only against the price;
- matchup, minutes and rest, with NO turning them around;
- injuries: avoid, probable, teammates, college;
- strong and thin leans;
- game-line matchup only while the price is open;
- the pool and combo limits;
- the background slate API, end to end.

**`backend/tests/test_slate_ai.py` (8):**
- parse guardrails (unknown ids, unsourced conflicts, combo sizes);
- the per-game news queries and ids;
- dropped legs kept out of assembly;
- code rejecting a combo that repeats a player;
- risks carried through;
- the Brave cap stopping news mid-slate while the model continues;
- no key, so briefs only;
- the wide pool;
- the news cache;
- fallback to rules on a model failure or when the model is off.

**Frontend:**
- `SlatePanel.test.tsx`: builds only on click, polls, shows combos and risks, "Put on docket", and the empty result. It also checks:
  - the model's synthesis: engine line, case and risk, stats-vs-news links, dropped legs, rules-only comparison;
  - the rules fallback reason.
- `Games.test.tsx`: the brief in the Docket.

## Gaps

- **Matchup:** no positional matchups (what a team allows to centers vs guards). ESPN's table is team-wide.
- **Teammates out:** listed, but there's no check of how he played without them.
- **Injuries:** long-term absences on the report look the same as tonight's late scratches.
- **Combos:** RFQ-priced, so the market figure is the legs multiplied, not Kalshi's quote. Use the Docket's quote check.
- **The model is a 12B local model:**
  - its judgment is only as good as the snippets it gets (titles and short descriptions, not full articles);
  - it can still misread a snippet, so every news-based claim links to its source for you to check.
- **Excerpts you paste in investigations** aren't fed to the slate build yet.
