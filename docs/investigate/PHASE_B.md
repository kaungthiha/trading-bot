# Investigate this pick: Phase B (real, deterministic evidence)

Follows `PHASE_A.md`. Still **no Brave search and no Ollama call**: every number comes from
code that already existed. The drawer now shows real data; the sample-data fixture is kept
for tests only.

## Backend
- **`app/investigate/`**
  - **`schemas.py`**: typed Pydantic contract (mirrors `InvestigationResult` in the frontend).
  - **`service.py`**: the deterministic builder.
- **Migration `0014_investigations`**: stores each canonical result, so the summary, the
  full view and `GET` all read the same object.
- **Routes (`app/api/investigate_routes.py`)**:
  - `POST /api/research/investigations` and `POST /api/research/investigations/{id}/refresh`
    need the `X-KRT-Request: research` header. Both are added to the pinned write-route sets
    in `test_api.py` / `test_signals.py`.
  - `GET /api/research/investigations/{id}`, `GET /api/research/preflight` and
    `GET /api/research/usage` are free. Preflight makes no ESPN call.
- **Config** (`.env.example` documents each one): `KRT_RESEARCH_BRAVE_DAILY_REQUEST_CAP`,
  `…_MONTHLY_REQUEST_CAP`, `…_MAX_SEARCHES_PER_INVESTIGATION`, `…_MAX_SOURCES_…` and
  `…_SEARCH_CACHE_HOURS`. These are app-side ceilings, not a Brave balance. The ledger that
  counts against them arrives in Phase C.

### What the builder reuses (no new maths)
- **Quote:** catalog ask for the side bought (NO ask = 1 − YES bid when unquoted), observed
  at the scan time. Fresh for 30 minutes.
- **Evidence:** `evidence_for` (ESPN box scores), the same check the Docket uses.
- **Price:** the slip check's `Fees`, `price_single` (all-in = ask + taker fee) and
  `walk_away`.
- **Injuries:** ESPN's injury report and team matching, the same as the Games injury strip.
- **Rules:** the event's rules excerpt and a link to the Kalshi market.

### Rules that keep it honest
- Box-score history is labelled a **frequency, not a calibrated probability**.
- The **conservative edge** (low end of the history range − all-in price) and the walk-away
  are shown only when all of these hold:
  - the quote is fresh;
  - there are 15+ games this season and the data isn't thin;
  - **tonight's lineup is normal**: no player out or doubtful on either team for team
    markets, and the player not injured for a prop.

  Otherwise the reasons are listed and the edge reads "Not enough evidence to estimate an
  edge".
- **Roster findings come first**, with their stance relative to the exact side (YES on a
  team with players out → against; the same fact supports the NO).
- **The takeaway is at most two sentences** and says what wasn't checked (news).
- **Every finding cites a source:** K1 Kalshi, E1 ESPN box scores, E2 ESPN injury report.
- **Cache key:** ticker | side | quote time | policy version. Bumping `POLICY_VERSION`
  invalidates old results. It was bumped to v2 when the roster rule was added; the live
  check showed a pre-rule cached result still being served.

### Found in the live check
Golden State to win (29¢ ask) first showed a **+7.2 pt conservative edge** from box scores,
on a night when Golden State had 6 players out (Curry, Butler, Green, Porziņģis…) and
Memphis 5. History can't see who's playing. That's why the roster rule exists. The same
investigation now leads with "Golden State Warriors: 6 out" against the pick and withholds
the edge.

## Frontend
- `apiSource` (default in the app) calls the routes above. Refresh uses the stored id.
- The price lens shows history with its range, labelled as frequency; the raw
  "history − all-in" marked "raw, not an edge"; and the conservative edge only when
  supported.
- The full view adds the Kalshi rules excerpt and link.
- An "unsupported" answer from preflight disables Run and shows the reason.

## Tests
- **Backend:** 11 new in `test_investigate.py`:
  - CSRF, catalog and ticker validation;
  - a prop using box scores and slip-check maths with every cited id existing;
  - YES ≠ NO (NO ask = 1 − YES bid), moneyline / spread distinct;
  - cache hit, then refresh recomputes, then GET returns the same summary;
  - a stale quote never gives an edge;
  - usage reports app caps only; supported-market checks;
  - no execution intents created;
  - players out withhold the edge and lead the findings, with opposite stance for NO;
  - the cache key carries the policy version, and the NO wording reads cleanly.
- `test_ops` migration head updated. Full backend suite passes, ruff clean.
- **Frontend:** 136 pass. New: the API source sends the CSRF header and exact contract,
  refreshes by id, renders history and the raw difference without inventing an edge, and an
  unsupported preflight disables Run.
- **Browser:** real GSW–MEM investigation at 1440 and 390; axe finds 0 violations in the
  drawer; Escape and focus return work. The phone summary runs slightly past one screen
  with real text (910 / 844 px).

## Next: Phase C
Brave discovery behind the explicit click:
- a durable, concurrency-safe usage ledger enforcing the caps;
- a rights-aware publisher registry (snippets and headlines only unless licensed);
- caching;
- exact game, date and line matching, and syndication de-duplication.
