import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { vi } from "vitest";

import type { CollectionGap, EvidenceAsOf, EvidenceSource } from "../api/types";
import { EvidencePanel } from "./EvidencePanel";

const cpi: EvidenceSource = {
  id: "fred:CPIAUCSL",
  title: "CPI All Items SA",
  series_id: "CPIAUCSL",
  category: "economics",
  frequency: "monthly",
  upstream_agency: "U.S. Bureau of Labor Statistics",
  source_page_url: "https://alfred.stlouisfed.org/series?seid=CPIAUCSL",
  license_notes: "Retrieved via FRED API under its Terms of Use.",
  attribution: "This product uses the FRED® API ...",
  release_timing_note: "BLS releases at 08:30 ET.",
  configured: true,
  record_count: 4,
  latest_vintage: "2026-11-10",
  latest_available_at: "2026-11-10T13:30:00+00:00",
  is_fresh: true,
  freshness_max_age_days: 45,
  last_run: null,
};
const unrate: EvidenceSource = {
  ...cpi,
  id: "fred:UNRATE",
  title: "Unemployment Rate",
  series_id: "UNRATE",
  configured: false,
  record_count: 0,
  latest_vintage: null,
  latest_available_at: null,
  is_fresh: false,
};

const view: EvidenceAsOf = {
  source_id: "fred:CPIAUCSL",
  as_of: "2026-11-18T15:00:00+00:00",
  items: [
    {
      observation_date: "2026-10-01",
      vintage_date: "2026-11-10",
      value: null,
      quality: "missing",
      available_at: "2026-11-10T13:30:00+00:00",
      retrieved_at: "2026-11-18T15:00:00+00:00",
      units: "Index 1982-1984=100",
      source_url: cpi.source_page_url,
    },
    {
      observation_date: "2026-09-01",
      vintage_date: "2026-10-15",
      value: "321.1",
      quality: "ok",
      available_at: "2026-10-15T12:30:00+00:00",
      retrieved_at: "2026-11-18T15:00:00+00:00",
      units: "Index 1982-1984=100",
      source_url: cpi.source_page_url,
    },
  ],
};

const gap: CollectionGap = {
  id: "g1",
  job: "kalshi_public",
  gap_start: "2026-11-18T01:00:00+00:00",
  gap_end: "2026-11-18T07:00:00+00:00",
  detected_at: "2026-11-18T07:00:00+00:00",
  backfillable: false,
  reason: "Quote snapshots were not collected.",
};

const calls: string[] = [];

beforeEach(() => {
  calls.length = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), "http://127.0.0.1");
      calls.push(url.pathname + url.search);
      const body =
        url.pathname === "/api/evidence/sources"
          ? { items: [cpi, unrate] }
          : url.pathname === "/api/collection-gaps"
            ? { items: [gap] }
            : url.pathname.endsWith("/observations")
              ? view
              : null;
      return body
        ? new Response(JSON.stringify(body), { status: 200 })
        : new Response("{}", { status: 404 });
    }),
  );
});
afterEach(() => vi.unstubAllGlobals());

describe("<EvidencePanel>", () => {
  it("lists sources with freshness and shows the as-of view with missing values", async () => {
    render(<EvidencePanel />);
    expect(await screen.findByText("FRESH")).toBeInTheDocument();
    expect(screen.getByText("NO DATA")).toBeInTheDocument();
    expect(screen.getByText("not scheduled")).toBeInTheDocument();
    expect(await screen.findByText("321.1")).toBeInTheDocument();
    const row = screen.getByText("2026-10").closest("tr")!;
    expect(within(row).getByText("MISSING")).toBeInTheDocument();
    expect(calls).toContain("/api/evidence/fred%3ACPIAUCSL/observations?limit=12");
  });

  it("refetches with an as_of timestamp when the user picks a time", async () => {
    render(<EvidencePanel />);
    await screen.findByText("321.1");
    const input = document.querySelector('input[type="datetime-local"]') as HTMLInputElement;
    fireEvent.change(input, { target: { value: "2026-10-15T08:00" } });
    await waitFor(() =>
      expect(calls.some((c) => c.includes("/observations?") && c.includes("as_of="))).toBe(true),
    );
  });

  it("shows collection gaps and whether they are recoverable", async () => {
    render(<EvidencePanel />);
    expect(await screen.findByText("not recoverable")).toBeInTheDocument();
    expect(screen.getByText(gap.reason)).toBeInTheDocument();
  });
});
