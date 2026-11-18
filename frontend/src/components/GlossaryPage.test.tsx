import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";

import App from "../App";
import { GlossaryProvider } from "../glossary/GlossaryContext";
import { ALL_TERMS } from "../glossary/terms";
import { GlossaryPage } from "./GlossaryPage";

function renderPage() {
  return render(
    <GlossaryProvider>
      <GlossaryPage />
    </GlossaryProvider>,
  );
}

describe("<GlossaryPage>", () => {
  it("lists every term and filters by search text and category", async () => {
    const user = userEvent.setup();
    renderPage();
    expect(screen.getByRole("status")).toHaveTextContent(`${ALL_TERMS.length} terms shown`);
    await user.type(screen.getByLabelText("Search terms"), "EV");
    expect(screen.getByText("Expected value")).toBeInTheDocument();
    await user.clear(screen.getByLabelText("Search terms"));
    await user.selectOptions(screen.getByLabelText("Category"), "contract");
    expect(screen.getByRole("status")).toHaveTextContent("3 terms shown");
    await user.type(screen.getByLabelText("Search terms"), "zzzz");
    expect(screen.getByRole("status")).toHaveTextContent("0 terms shown");
  });

  it("has worked examples for edge, slippage and Brier score using shared Term triggers", () => {
    renderPage();
    const ex = screen.getByRole("region", { name: "Try it" });
    for (const id of ["edge", "slippage", "brier-score"]) {
      expect(ex.querySelector(`[data-term-id="${id}"]`)).not.toBeNull();
    }
  });

  it("'Learn more' opens the detailed dialog", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole("button", { name: "Learn more about Slippage" }));
    expect(screen.getByRole("dialog", { name: "Slippage" })).toBeInTheDocument();
  });
});

describe("App navigation and jargon audit", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 404 })));
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    window.location.hash = "";
  });

  it("navigates to the glossary via the hash route", async () => {
    window.location.hash = "#/glossary";
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Glossary", level: 2 })).toBeInTheDocument();
    const nav = screen.getByRole("navigation", { name: "Primary" });
    expect(within(nav).getByRole("link", { name: "Glossary" })).toHaveAttribute("aria-current", "page");
  });

  it("explains jargon at first meaningful occurrence without repeating triggers per panel", () => {
    window.location.hash = "";
    const { container } = render(<App />);
    for (const panel of container.querySelectorAll("section.panel")) {
      const counts = new Map<string, number>();
      for (const el of panel.querySelectorAll("[data-term-id]")) {
        const id = el.getAttribute("data-term-id")!;
        counts.set(id, (counts.get(id) ?? 0) + 1);
      }
      for (const [id, n] of counts) expect(n, `${id} marked ${n}x in one panel`).toBeLessThanOrEqual(2);
    }
  });
});
