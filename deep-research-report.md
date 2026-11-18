# Developer Foundation for a Human-in-the-Loop Kalshi Research Bot

## Deliverable

I created a developer-ready Markdown research pack organized so that each file is independently usable while the README serves as the implementation index. The complete repository-style bundle is available as a ZIP: [download the full Kalshi research-bot foundation](sandbox:/mnt/data/kalshi-research-bot-foundation.zip). The two most useful entry points are the [README](sandbox:/mnt/data/kalshi-research-bot-foundation/README.md) and the [source index](sandbox:/mnt/data/kalshi-research-bot-foundation/SOURCES.md).

The proposed repository is:

```text
kalshi-research-bot-foundation/
├── README.md
├── 00_SCOPE_AND_PRINCIPLES.md
├── 01_KALSHI_API_AND_COMPLIANCE.md
├── 02_DATA_SOURCES.md
├── 03_NORMALIZATION_AND_ADAPTERS.md
├── 04_DATABASE_AND_MIGRATIONS.md
├── 05_MODELS_AND_STRATEGIES.md
├── 06_BACKTESTING_AND_EVALUATION.md
├── 07_ARCHITECTURE_AND_SECURITY.md
├── 08_API_CONTRACTS_AND_EXECUTION.md
├── 09_MVP_ROADMAP_AND_TESTS.md
├── 10_AGENT_HANDOFF_PROMPTS.md
├── 11_VERIFY_BEFORE_CODING.md
└── SOURCES.md
```

The bundle covers the current Kalshi API surface and authentication model; exchange mechanics, fees, market lifecycle, order-book semantics, historical data and rate limits; a source-by-source data strategy for macroeconomics, NBA, culture/news and technology; normalized schemas and event-surface adapters; Supabase migrations/RLS; probabilistic models and execution math; point-in-time backtesting; a threat model and explicit-approval protocol; engineering acceptance tests; and copy/paste implementation prompts for a coding agent. Kalshi currently documents separate production and demo APIs, API-key signing with RSA-PSS or Ed25519, WebSocket feeds, live/historical data separation, and token-bucket rate limits; its Basic prediction tier currently provides 200 read tokens/s and 100 write tokens/s, with most authenticated calls costing 10 tokens unless an endpoint specifies otherwise. citeturn966503view1turn966503view2turn357009view1turn357009view3

## Findings that materially change the design

The most important result of the research is not an algorithm—it is a set of **data-rights constraints that should be resolved before production coding**. Kalshi explicitly offers its Trade API for programmatic access to market data, portfolios, orders, and order books. citeturn286506search1turn966503view1 However, Kalshi's separate Data Terms are exceptionally broad: they state that website “Kalshi Data” is for personal, non-commercial use; say that software development using such data requires prior written consent; prohibit scraping, systematic retrieval and compilation; prohibit various financial-product/service uses without consent; and expressly prohibit using Kalshi Data in connection with AI/ML. citeturn738403view0turn756164view1turn756164view2

Those terms and the documented developer/trading API are not sufficiently reconciled in the public materials I found. I would therefore treat **written clarification from Kalshi** as a production launch blocker covering API market-data retention, statistical analysis, backtesting, derived signals, use of a coding agent, and personal automated execution after manual approval. The pack deliberately says *do not scrape Kalshi HTML* and recommends developing the coding-agent integration against synthetic fixtures until that question is resolved. That is more conservative than assuming that possession of an API key grants every downstream data right contemplated by the project. citeturn286506search9turn286506search1

NBA data creates a second major constraint. The NBA's Terms of Use, last updated July 13, 2026, state that NBA Statistics may be used for legitimate news reporting or private non-commercial purposes but may not be used “in connection with any gambling activity,” expressly including legal gambling activity, and also restrict real-time/play-by-play statistical database uses. That means `stats.nba.com`, undocumented NBA JSON endpoints, and open-source wrappers around those endpoints should **not** be assumed lawful inputs to a Kalshi NBA model merely because they are technically accessible. citeturn672085search4 The league's official injury reports are nonetheless valuable for understanding status timing—the current 2026–27 reporting regime generally requires a report by 5 p.m. local the prior day, different timing for the second game of a back-to-back, game-day reports, and continual updates—but systematic trading use should still be cleared against applicable terms or replaced with a properly licensed sports feed. citeturn672085search0turn672085search14

FRED has a comparable, though less obvious, issue: its API Terms contain a prohibited-use provision referring to applications used “in connection with gambling.” citeturn918425search0 Because a CFTC-regulated event contract and legal “gambling” are not concepts I would equate without legal analysis, the pack does not make that leap in either direction. It recommends using the underlying BLS, BEA, Census, Treasury and Federal Reserve sources for production unless FRED clarifies the use. FRED/ALFRED remain technically excellent for research because ALFRED records when data were initially released and subsequently revised, which is exactly what a leakage-safe macro backtest needs. citeturn672085search1turn672085search2turn672085search3turn672085search5

There is also a deployment caveat around GitHub Pages. GitHub Pages is static hosting rather than a server-side runtime, and GitHub's Pages documentation says the service is not intended as free hosting for sites primarily facilitating commercial transactions and should not be used for sensitive transactions. citeturn632547search0turn632547search4 For that reason, the research pack treats Pages as an excellent documentation/read-only research surface, but recommends verifying its suitability before making it the live approval interface. A local approval client or separately hosted authenticated UI is the clean fallback.

## Data and model foundation

For macro markets, the best low-cost primary-source stack is stronger than relying solely on FRED. BLS currently exposes registered API access with up to 500 daily queries, 50 series per query, and 20 years per query, while its unregistered limits are substantially smaller. citeturn918425search3turn918425search4 BEA provides an official API and documents throttling/429 behavior; Census publishes a current developer API; Treasury's Fiscal Data API requires no token and makes fiscal datasets available through structured formats; and the Federal Reserve publishes official release/RSS feeds suitable for event triggering. citeturn918425search5turn918425search8turn918425search6turn349199search0turn349199search2 The pack therefore makes macro the recommended first production-quality model surface.

For culture and technology, the architecture intentionally separates **discovery** from **proof**. The NYT Article Search API exposes article metadata such as headlines, abstracts, snippets, lead paragraphs, URLs, publication dates and other metadata; it is not an API for obtaining arbitrary full subscription article bodies. citeturn414502search1turn414502search4 The bundle therefore treats your NYT subscription and developer API as distinct rights: use the API fields the API actually returns and link to paywalled stories rather than scraping them. GDELT is useful for coverage discovery, outlet/domain information, counts, themes and contextual search, but API throttling exists and the underlying publisher's article remains that publisher's content. citeturn414502search18turn414502search6turn414502search27 SEC EDGAR, company investor-relations feeds, GitHub's official API, government RSS feeds and official vendor blogs are much better sources for resolving technology/company events. SEC currently asks automated EDGAR clients to identify themselves and keep automated request rates at or below 10 requests per second. citeturn814058search7turn814058search8

Google Trends is useful but should not be a hard MVP dependency. As of November 17, 2026, Google's official Trends API is still described as a limited-access alpha, with a rolling five-year history, consistent scaling across requests and daily/weekly/monthly/yearly aggregation; it is not a generally open API that every project can assume access to. citeturn414502search0turn414502search2 Wikimedia offers useful entity and attention data but has explicit API usage/rate policies and requires appropriate client identification. citeturn814058search0turn414502search36

The modeling chapter is deliberately centered on probability quality rather than “signals that look profitable.” Brier score and logarithmic loss are proper scoring approaches for probabilistic forecasts; they complement calibration/reliability diagnostics and prevent a high hit-rate model from being mistaken for a well-calibrated forecaster. citeturn293831search0turn293831search5 Macro modeling starts with transparent time-series/dynamic-regression baselines before advancing to nowcasting methods designed for staggered economic releases and “jagged-edge” real-time data. citeturn293831search2 NBA sections specify Elo as a baseline and Poisson/negative-binomial score models as candidates rather than presupposing one distribution is correct. Market microstructure is treated explicitly: spreads can arise from adverse selection, and a passive maker order can have worse conditional expected value precisely because informed traders are more likely to hit stale quotes. citeturn293831search3

The pack also avoids equating a prediction-market price mechanically with the objectively correct probability. Prediction markets can aggregate information effectively, but the interpretation of prices as beliefs depends on assumptions about traders, utility, wealth, market structure and frictions. citeturn984828search0turn984828search10turn984828search2 That distinction matters when measuring the model's incremental information over the market.

## Trading and backtesting design

The execution math in the files operates on **executable prices**, not midpoints. Kalshi's current order-book representation exposes YES and NO bid ladders; the opposing best bid implies the ask because YES and NO are complementary claims. REST is a point-in-time snapshot, so live research should use WebSocket updates and then perform a fresh preflight snapshot immediately before any order. citeturn662335view1 The files include depth-aware VWAP calculations and require fees and slippage to be subtracted before calling something an edge.

For example, if the model estimates `P(YES)=0.63`, ten contracts are actually available at `0.55`, and an illustrative current fee calculation gives approximately `$0.17325` before exchange rounding, gross informational EV is `10 × (.63-.55) = $0.80`; after that fee and a `$0.05` slippage allowance, estimated EV is approximately `$0.57675`. But the proposed decision rule does **not** trade merely because that number is positive: if the lower confidence bound of the calibrated forecast does not clear the executable break-even price plus fees, slippage and a model-risk margin, the system abstains. Current Kalshi fees are series-dependent and mutable: the live schedule currently identifies most markets as taker-fee markets while some categories have separate maker treatment, so the code is instructed not to hardcode one universal 2026 fee equation. citeturn756164view0turn972987search8turn972987search6

The backtesting plan uses `available_at` rather than simply an observation's period/date. This prevents a January statistic revised in March from appearing in a February trading simulation. ALFRED's documentation illustrates exactly this distinction by storing real-time periods and vintage dates. citeturn672085search1turn672085search3turn672085search5 Walk-forward validation replaces random train/test splitting, calibration is trained only on out-of-sample forecasts, and fills are simulated from bid/ask or available depth rather than midpoint. The pack also separates forecast metrics—Brier, log loss and calibration—from trading metrics such as after-fee P&L, drawdown, premium at risk, fill quality and edge decay.

“Arbitrage” is treated conservatively as well. Two apparently complementary markets are not an arbitrage unless their state-contingent payouts really are identical after reading the actual rules, resolution sources, timing, rounding, depth and fees. Execution latency, partial fills, different settlement criteria and adverse selection are enough to turn an apparent free profit into ordinary relative-value risk. Kalshi's own lifecycle documentation also makes close, determination, dispute/amendment and finalization separate states, another reason not to reason solely from contract titles. citeturn662335view3turn662335view2

## Security and approval architecture

Supabase is a good fit for the proposed boundary because its current architecture explicitly distinguishes public/publishable browser keys from backend secret keys: publishable keys are expected to be visible to clients and depend on RLS, whereas secret/service-role credentials bypass RLS and must remain on trusted servers. citeturn960725search1turn960725search0turn960725search6 Hosted Supabase can schedule work through Cron/`pg_cron` and invoke Edge Functions, which is sufficient for lightweight polling and event-driven collectors. citeturn960725search2turn960725search3 Current free-tier resources are enough for an MVP but not an excuse to capture every full-depth quote indefinitely; free quotas and Edge Function limits remain finite and should be verified in the project dashboard at deployment. citeturn960725search4turn960725search5turn960725search7

The key architectural invariant is:

```text
external evidence
      ↓
normalized observations
      ↓
feature snapshot
      ↓
model forecast
      ↓
research proposal
      ↓
USER APPROVES EXACT HASHED PAYLOAD
      ↓
server-side preflight
      ↓
server-side Kalshi signing
      ↓
one idempotent order submission
      ↓
reconciliation / fills / settlement
```

The browser never sees the Kalshi private key. The approval hash binds market, YES/NO side, buy/sell action, quantity, limit price, fee and slippage caps, quote snapshot, rules hash and expiration. After approval, the server re-fetches market status, order book and applicable fee information; if the quote has deteriorated, the rules/status changed, the approval expired, or a hard risk/compliance limit is violated, the server sends **no order** and a fresh approval is required. Kalshi itself requires signed authenticated requests using a private key and a timestamp currently constrained to within 30 seconds of the exchange clock, reinforcing why signing belongs server-side rather than in GitHub Pages JavaScript. citeturn966503view1

The database migrations in the pack keep research tables separate from approvals/order intents and default every environment to `live_trading_enabled=false` plus `kill_switch=true`. The suggested controls—maximum contracts per order, maximum premium at risk, correlated-factor limits, maximum open positions and a kill switch—are safety rails rather than autonomous bankroll management. The user still chooses whether to approve each exact trade.

## Recommended implementation sequence and remaining blockers

The highest-value MVP is narrower than a four-domain live bot: build the normalized market/rules engine, source registry, point-in-time observation store and paper-trading machinery first; then make macroeconomic contracts the first end-to-end model because they have the strongest official structured-data ecosystem. Add culture/technology event detection using RSS, SEC, official-company sources, NYT metadata and GDELT discovery next. Keep the NBA adapter in synthetic/licensed-data research mode until an acceptable data license is identified. Finally, add Kalshi **demo** execution with exact human approval, stale-quote protection and idempotent reconciliation before considering a limited live pilot. Kalshi's demo credentials and balances are intentionally separate from production and demo market behavior is not guaranteed to mirror production, so demo validates integration rather than expected profitability. citeturn704035search16turn357009view2

The pack's [“what to verify before coding” checklist](sandbox:/mnt/data/kalshi-research-bot-foundation/11_VERIFY_BEFORE_CODING.md) should be treated as a gating document rather than optional documentation. In particular, four issues remain intentionally marked unresolved: the application of Kalshi's Data Terms to a personal API-driven statistical trading bot; FRED's “gambling” restriction as applied to regulated event contracts; a free NBA statistics license that explicitly permits this prediction-market use; and the exact current NYT API quota/retention terms for the user's developer account. The research does not invent answers to those questions.

For implementation with Fable/Opus, [the agent handoff file](sandbox:/mnt/data/kalshi-research-bot-foundation/10_AGENT_HANDOFF_PROMPTS.md) provides specs for repository scaffolding, immutable normalized types, a PIT backtester, the human-approval flow, macro adapters and news-event extraction. The overarching design is deliberately shaped so that an agent can write substantial code without ever receiving a production Kalshi key or unrestricted raw production data—a particularly useful safeguard given Kalshi's current data-use language. citeturn756164view2turn286506search1