import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";

import type { CpiForecast, MetricSummary, ModelCard, ModelEvaluation } from "../api/types";
import { ModelsPanel } from "./ModelsPanel";

const card: ModelCard = {
  name: "gaussian_trailing",
  version: "1.0.0",
  summary: "Normal distribution centred on the recent average first-print MoM.",
  contract_type: "Headline CPI-U SA MoM first print > threshold",
  features: "Mean of last 12...",
  uncertainty_method: "Heuristic sensitivity band. NOT a confidence interval.",
  hyperparameters: { k_mean: 12 },
  limitations: ["Forecasts only the NEXT unreleased month; abstains otherwise."],
};

const summary = (n: number, brier: number): MetricSummary => ({
  n_predictions: n,
  n_events: n / 8,
  n_abstained: 8,
  base_rate: 0.437,
  brier,
  log_loss: 0.4784,
  log_loss_eps: 1e-6,
  calibration: [
    { lower: 0.4, upper: 0.5, count: 120, mean_p: 0.45, observed_rate: 0.43 },
    { lower: 0.5, upper: 0.6, count: 0, mean_p: null, observed_rate: null },
  ],
});

const evaluation: ModelEvaluation = {
  id: "e1",
  created_at: "2026-11-18T22:37:00Z",
  model: "gaussian_trailing",
  version: "1.0.0",
  feature_version: "cpi_first_print_mom.v1",
  dataset_hash: "c6ff5fd82633aaaa",
  config: {
    thresholds: ["0.1"],
    holdout_start: "2015-01-01T00:00:00Z",
    dev_range: ["1972-05-01", "2014-11-01"],
    holdout_range: ["2014-12-01", "2026-10-01"],
  },
  dev: summary(3800, 0.1382),
  holdout: summary(1120, 0.1559),
  data_notes: { first_prints_used: 652, excluded: { earliest_vintage_not_a_first_print: 304 } },
};

function forecastFor(threshold: string): CpiForecast {
  const offGrid = threshold === "9"; // abstention rendering (not reachable via the dropdown)
  return {
    contract_key: `CPI_MOM_SA_FIRST>${threshold}@2026-11`,
    reference_month: "2026-11-01",
    threshold,
    as_of: "2026-11-18T22:37:00Z",
    forecasts: [
      {
        model: "gaussian_trailing",
        version: "1.0.0",
        decision: offGrid ? "ABSTAIN" : "FORECAST",
        p_yes: offGrid ? null : threshold === "0.3" ? 0.482 : 0.7,
        lower: offGrid ? null : 0.37,
        upper: offGrid ? null : 0.597,
        uncertainty_method: card.uncertainty_method,
        reasons: offGrid ? ["THRESHOLD_OFF_GRID"] : [],
        inputs: {},
      },
    ],
    recent_prints: [{ month: "2026-10", mom_rounded: "0.4", released_at: "2026-11-10T13:30:00Z" }],
    caveat: "Model probabilities are estimates ... not trade recommendations.",
  };
}

const calls: string[] = [];

function stub(evals: ModelEvaluation[]) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), "http://127.0.0.1");
      calls.push(url.pathname + url.search);
      const body =
        url.pathname === "/api/models"
          ? [card]
          : url.pathname === "/api/models/metrics"
            ? evals
            : url.pathname === "/api/research/cpi-mom/forecast"
              ? forecastFor(url.searchParams.get("threshold") ?? "")
              : null;
      return new Response(JSON.stringify(body ?? {}), { status: body ? 200 : 404 });
    }),
  );
}

beforeEach(() => {
  calls.length = 0;
});
afterEach(() => vi.unstubAllGlobals());

describe("<ModelsPanel>", () => {
  it("shows forecast with band, evaluation sample sizes, and model card", async () => {
    stub([evaluation]);
    render(<ModelsPanel />);
    expect(await screen.findByText("48.2%")).toBeInTheDocument();
    expect(screen.getByText("37.0% – 59.7%")).toBeInTheDocument();
    expect(screen.getByText("CPI_MOM_SA_FIRST>0.3@2026-11")).toBeInTheDocument();
    const holdout = (await screen.findByText(/Holdout 2014-12-01/)).closest("tr")!;
    expect(within(holdout).getByText("1120")).toBeInTheDocument();
    expect(within(holdout).getByText("140")).toBeInTheDocument();
    expect(within(holdout).getByText("0.1559")).toBeInTheDocument();
    expect(screen.getByText(/652 first prints used/)).toBeInTheDocument();
    expect(screen.getByText(/not trade recommendations/)).toBeInTheDocument();
    const warn = screen.getByRole("note", { name: "Model limitations" });
    expect(warn).toHaveTextContent(/Forecasts only the NEXT unreleased month/);
    expect(screen.getAllByText(/Forecasts only the NEXT unreleased month/)).toHaveLength(2);
  });

  it("refetches when the threshold changes; shows empty-evaluation hint", async () => {
    stub([]);
    const user = userEvent.setup();
    render(<ModelsPanel />);
    await screen.findByText("48.2%");
    await user.selectOptions(screen.getByLabelText(/Threshold/), "0.5");
    await waitFor(() =>
      expect(calls).toContain("/api/research/cpi-mom/forecast?threshold=0.5"),
    );
    expect(await screen.findByText("70.0%")).toBeInTheDocument();
    expect(screen.getByText(/No evaluation stored yet/)).toBeInTheDocument();
  });

  it("renders ABSTAIN with its reason codes", async () => {
    stub([]);
    const user = userEvent.setup();
    render(<ModelsPanel />);
    await screen.findByText("48.2%");
    // Inject an off-grid option to exercise the abstention path.
    const select = screen.getByLabelText(/Threshold/) as HTMLSelectElement;
    select.add(new Option("> 9%", "9"));
    await user.selectOptions(select, "9");
    expect(await screen.findByText("THRESHOLD_OFF_GRID")).toBeInTheDocument();
    expect(screen.getByText("ABSTAIN")).toBeInTheDocument();
  });
});
