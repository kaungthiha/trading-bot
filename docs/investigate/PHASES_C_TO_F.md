# Investigate this pick: Phases C–F report

Follows `PHASE_A.md` and `PHASE_B.md`. Built while the owner was away. **No real Brave Search
request was made at any point**: every search test uses a mocked transport, and the live
browser check routed all research calls to a temporary backend with search disabled. The app's
ledger reads 0 research searches.

## Brave Search: what was verified (from Brave's public docs, 2026-11-20)
- **Endpoint:** news is `https://api.search.brave.com/res/v1/news/search`, with the key in the
  `X-Subscription-Token` header (what the app already used). The `freshness` options include
  `pw`, the past week. Web search and `extra_snippets` aren't used (which plan includes extra
  snippets is ambiguous).
- **Price:** "$5 per 1,000 requests" with "$5 in free credits every month" (the page also
  says "up to $20", which conflicts). **The balance can't be read through the API**, and the
  app never claims to know it.
- **Rate limits:** 429 behaviour and rate-limit headers aren't documented. The app treats a
  429 as final (no retry).
- **Storage terms:** the ToS forbid storing, caching or building a database of results
  "other than transient storage required for operation". So:
  - the search cache is **in memory only**, expires after `KRT_RESEARCH_SEARCH_CACHE_HOURS`,
    and is cleared on restart;
  - snippets are never written to disk (tested);
  - within the cache window, a stored investigation keeps each source's headline, link,
    publisher and date, so a cached result can be shown again;
  - **after the cache window (the investigation's `stale_at`), news is deleted from the stored
    copy** (`service.purge_expired_news`, decided by the owner). This covers the sources and
    everything written from them: findings citing an article, the model's unsourced findings,
    takeaway, gaps and stance. The app's own facts stay: box scores, the injury-report roster
    finding, the college lineup warning and the price assessment. The takeaway then says the
    articles were removed and to refresh. The purge runs at startup and on every research
    request, never searches, and is tested in `tests/test_research_retention.py`.

## Phase C: bounded discovery and source controls
- **Ledger (`investigate/ledger.py`, migration `0015_search_ledger`):**
  - a row is written before every network attempt, retries included, since each is billed;
  - the check-and-insert runs inside SQLite `BEGIN IMMEDIATE` plus a process lock, and 40
    concurrent attempts against a cap of 20 give exactly 20 (tested);
  - day and month caps are counted in UTC, and only a hash of the query is stored;
  - the app's other Brave uses (AI-review headlines, the news route) are recorded under their
    own purpose but don't count against the research caps.
- **Client:** research searches use `max_retries=0`. The client calls the ledger hook before
  every attempt; a full budget raises before anything is sent.
- **Publisher registry (`investigate/registry.py`, version `2026-11-20.1`):** covers NBA.com,
  ESPN, AP, RotoWire, CBS, NBC, The Athletic, NYT, Covers, Pickswise, Boyd's Bets, PickDawgz,
  Sports Betting Dime, Sportsbook Review and Action Network. Each entry records discovery
  (Brave metadata), full-text permission, retention, attribution, priority and enabled.
  - **No publisher currently permits full-text processing.** The app never fetches a publisher
    page (so no paywall, robots or CAPTCHA question arises) and labels sources "headline only"
    or "headline and snippet".
  - Unlisted publishers are allowed as metadata at the lowest weight.
- **Search (`investigate/search.py`):**
  - **Queries:** at most 3, tailored to the market (matchup preview; injury report or player
    status; a spread, total or prop angle with the line), de-duplicated.
  - **Relevance:** a result must name a team nickname (or the prop player's surname).
  - **Matching:** published 3+ days before the game → `past_matchup`. A different .5 line in
    the plausible range for the market → `different_line`. Our line → `exact`, which ranks
    first.
  - **De-duplication:** canonical URLs (www/m/amp and query strings) collapse; near-identical
    titles across publishers are marked `duplicate_of` ("not independent").
  - **Trimming and failures:** results are cut to `max_sources`. Not configured, budget used
    up, 429, outage and no results each produce a plain-language note.
- **Only explicit actions search:** the search runs only inside POST run and refresh.
  Preflight, GET, page loads and expanding the full view can't (tested at the API level).

## Phase D: local Ollama synthesis (`investigate/synth.py`)
- **Inputs:** the pick, the app's numbers (pre-formatted, so the model has no arithmetic to
  do), the deterministic findings, and each source's headline and snippet labelled UNTRUSTED
  DATA. The model has no tools.
- **Output:** a JSON schema of claims, takeaway, up to 3 findings, gaps and stance. It's
  validated **fail-closed**:
  - unknown source ids are removed, and a factual or statistical finding left without a source
    is marked *unverified*;
  - any number not in the evidence marks a finding unverified, or replaces the takeaway with
    the deterministic one;
  - hype ("lock", "guaranteed", "easy money", "AI-approved") is rejected;
  - instruction-like or credential-like text (ignore-instructions, API keys, `KRT_`, URLs,
    "place an order", `/api/`) is dropped;
  - claims from a different-line or past-matchup source become neutral, prefixed with the
    reason;
  - betting-site "facts" become analyst opinion, and syndicated copies collapse to one source;
  - a counterargument is mandatory, and the players-out fact always stays in the top 3.
- **Limits:** one synthesis at a time (a second waits 5 s, then falls back with a "busy"
  note), and a 90 s model timeout. The model name is part of the cache key.
- **Fallback:** Ollama offline, invalid JSON or a non-Ollama provider leaves the deterministic
  summary, with a note.
- **Live, on the real local model (gemma4:12b, ~17 s, no search):** "The evidence is
  insufficient to support a confident pick because Golden State is missing six players,
  including Stephen Curry. While historical win frequency is 50%, the current lineup is not
  reflected in past data." All findings were verified and none were dropped.

## Phase E: broader entry points
- **Docket:** unchanged. Unsupported legs explain why.
- **Ideas tab:** every single has *Investigate* (live: 10 of 10).
- **Markets event view:** NBA single-game events get *Investigate* per row (live: 2 rows on
  GSW–MEM); other events show none (live: 0 on the "Best AI" event).
- **Scanner cards:** a leg gets *Investigate* only when it's an NBA single-game market. Current
  cards are non-sports, so none show.
- **NHL: not enabled.** (Men's and women's college basketball and the WNBA were added
  afterwards: see `COLLEGE.md`.)

## Phase F: quality
- **Tests:**
  - backend 423 pass (34 for investigation: 11 deterministic, 13 search/ledger/registry,
    11 synthesis), ruff clean;
  - frontend 137 pass, typecheck clean, build OK, bundle secret scan clean;
  - execution, paper and approval tests unchanged and passing; no execution intents are
    created by investigations (tested).
- **Browser:** GSW–MEM at 1440 and 390 with research routed to the search-free backend. axe
  finds 0 violations in the drawer; Escape closes it; focus returns; the slip is unchanged;
  0 requests reached the normal backend's research routes.
- **Financial maths:** unchanged. The investigation reuses `Fees`, `price_single` and
  `walk_away` and adds none of its own.

## Acceptance checklist (spec §8)
| Requirement | Where it's proven |
| --- | --- |
| Summary by default; full research collapsed | `Investigate.test.tsx` |
| ≤2 sentences, ≤3 findings, sources accessible | clamp tests (frontend), schema `max_length=3`, synth clamp |
| Opening/closing keeps the pick and slip | drawer test, browser walkthrough |
| YES vs NO, moneyline vs spread, distinct lines | frontend hypothesis tests, backend `test_yes_and_no…` |
| Quote, article and model age; missing price/model explicit | drawer and price-lens tests; sources carry published/retrieved |
| Expanding makes zero Brave/Ollama calls | frontend run counter; backend GET/preflight never search or call the model |
| Re-renders don't duplicate jobs | store de-dup test |
| Daily/monthly caps under concurrency | `test_caps_hold_under_concurrent_requests`, `test_monthly_cap…` |
| Cache hit, downtime, no results, budget exhausted | `test_cache_hits…`, `test_429…`, `test_not_configured…`, `test_budget_exhausted…` |
| Past matchup / different line not support | `test_relevance…`, synth `test_different_line…` |
| Syndication not independent | `test_relevance…`, synth `test_syndicated…` |
| Unapproved full text not fetched or stored | registry test (none permitted), snippets-never-stored tests |
| Prompt injection can't reach credentials or execution | `test_prompt_injection…`, `test_api_injected_article…` |
| Invalid source ids / invented numbers rejected or unverified | `test_invented_sources_and_numbers…` |
| Ollama offline → useful deterministic result | `test_failures_keep…`, `test_api_model_offline…` |
| Keyboard, Escape, labels, narrow layout | drawer tests, axe at 1440/390 |
| No regressions in scanner, history, paper, execution | full suites pass |
| No real orders | no execution code touched; the intents list stays empty |

## Known limits and gaps
- **NBA only** (see Phase E). Totals and props use team and player names from ESPN; Kalshi
  codes that ESPN spells differently rely on the existing alias table.
- **Line matching is heuristic** (.5 numbers in headlines and snippets). Unclear text is
  "unknown", never "exact".
- **The summary is only as good as Brave's snippets:** with no licensed full text, the model
  never reads whole articles, and the UI says so.
- **The summary takes ~15–20 s on this machine** and blocks the drawer's Run (it shows
  progress). It's synchronous rather than a background job.
- **Stored headlines and links** are kept only for the cache window, then deleted (see the
  storage terms above). There's no timer: an expired row is cleaned at the next startup or
  research request.
- **Strict about model text:** after the window, the model's findings that cite no source are
  removed too, since they may paraphrase a headline. The app's own sourceless notes ("History
  covers 15 games") go with them when a model summary was used.
