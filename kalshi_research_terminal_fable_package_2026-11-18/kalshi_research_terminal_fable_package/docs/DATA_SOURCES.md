# External Evidence Sources and Licensing

## Adapter rules
Each `EvidenceAdapter` documents source URL, exact retrieval method, authentication, license/usage limitations, rate limits, update cadence, publication timestamp, first usable/available timestamp, revision history, freshness threshold, deduplication and retry/backfill. Distinguish a source reporting that something was *announced* from an official source determining *contract settlement*.

## Economics: start here
- [FRED / ALFRED](https://fred.stlouisfed.org/docs/api/fred/overview.html): archived/vintage economic time series, subject to registration/licensing. Use real-time vintage dates for backtests; [vintage API](https://fred.stlouisfed.org/docs/api/fred/series_vintagedates.html).
- [BLS API](https://www.bls.gov/audience/developers.htm): official labor/CPI-related data. Watch revisions and release times.
- [BEA API](https://apps.bea.gov/API/docs/): national accounts/GDP.
- [Census APIs](https://www.census.gov/data/developers.html): structured government datasets.
- [Treasury Fiscal Data](https://fiscaldata.treasury.gov/api-documentation/): government fiscal data and release information.

## Technology/company
- [SEC EDGAR developer resources](https://www.sec.gov/about/developer-resources): official company filings and extracted XBRL, with SEC access policies and user agent requirements.
- [GitHub REST API](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api): repository releases/activity where directly relevant, obey auth and limits.
- First-party company newsrooms/release notes/RSS: verify usage rights and source reliability before adding.

## Culture/news
- [GDELT](https://gdeltproject.org/data.html) for discovery and coverage trends, **not** authoritative event resolution by itself.
- NYT API: subscription access does **not** imply permission to retrieve full subscriber article content by API. Verify developer account entitlement, API fields, and terms. No paywall bypass.
- Structured award body/official announcement sites: first choice when contract rules explicitly reference them.

## NBA
Select a documented, reliably licensed source with game schedules, final scores and pregame availability timestamps. Do **not** assume unofficial NBA stats endpoints permit automated scraping. MVP can use hand-imported documented CSV or fixtures until source selected. Track injuries separately with timestamps and source reliability; never build pregame features from postgame box scores.

## Source ranking
Contract's official determination source > authoritative first-party data > official public API > reputable secondary reports > web/news mentions. Human confirmation required for conflicting/missing rule sources. Never pretend the highest-ranked source is infallible; retain full evidence trail and discrepancy statuses.
