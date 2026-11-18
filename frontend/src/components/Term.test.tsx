import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { GlossaryProvider } from "../glossary/GlossaryContext";
import { TERMS } from "../glossary/terms";
import { Term, TOOLTIP_CLOSE_DELAY_MS } from "./Term";

const wait = (ms: number) => new Promise((r) => setTimeout(r, ms));

function renderWithProvider(ui: React.ReactNode) {
  return render(
    <GlossaryProvider>
      <p>
        before <button type="button">other</button> {ui}
      </p>
    </GlossaryProvider>,
  );
}

describe("<Term> tooltip", () => {
  it("shows a non-interactive tooltip on focus; Escape hides it and keeps focus", async () => {
    const user = userEvent.setup();
    renderWithProvider(<Term id="spread">spread</Term>);
    const trigger = screen.getByText("spread");
    await user.tab();
    await user.tab();
    expect(trigger).toHaveFocus();
    const tip = screen.getByRole("tooltip");
    expect(tip).toHaveTextContent(TERMS.spread.shortDefinition);
    expect(trigger).toHaveAttribute("aria-describedby", tip.id);
    expect(tip.querySelector("a, button, input, [tabindex]")).toBeNull();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("tooltip")).toBeNull();
    expect(trigger).toHaveFocus();
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("shows on hover, stays open while the pointer is over the tooltip, hides on leave", async () => {
    const user = userEvent.setup();
    renderWithProvider(<Term id="bid">bid</Term>);
    await user.hover(screen.getByText("bid"));
    const tip = screen.getByRole("tooltip");
    await user.hover(tip); // hoverable (WCAG 1.4.13)
    await wait(TOOLTIP_CLOSE_DELAY_MS * 2);
    expect(screen.getByRole("tooltip")).toBeInTheDocument(); // still open after the grace period
    await user.unhover(tip);
    await user.unhover(screen.getByText("bid"));
    await waitFor(() => expect(screen.queryByRole("tooltip")).toBeNull());
  });

  it("touch: no hover tooltip, a tap opens the detailed dialog", async () => {
    renderWithProvider(<Term id="edge">edge</Term>);
    const trigger = screen.getByText("edge");
    fireEvent.pointerEnter(trigger.parentElement!, { pointerType: "touch" });
    fireEvent.mouseEnter(trigger.parentElement!);
    expect(screen.queryByRole("tooltip")).toBeNull();
    fireEvent.click(trigger);
    expect(screen.getByRole("dialog", { name: "Edge" })).toBeInTheDocument();
  });
});

describe("<Term> detail dialog", () => {
  it("Enter opens a modal dialog with deep explanation, formula, sources; Escape returns focus", async () => {
    const user = userEvent.setup();
    renderWithProvider(<Term id="brier-score">Brier score</Term>);
    const trigger = screen.getByText("Brier score");
    trigger.focus();
    await user.keyboard("{Enter}");
    const dialog = screen.getByRole("dialog", { name: "Brier score" });
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(dialog).toHaveTextContent(TERMS["brier-score"].deepExplanation);
    expect(dialog).toHaveTextContent("mean((p − y)²)");
    expect(screen.getByRole("button", { name: "Close definition" })).toHaveFocus();
    expect(screen.getByRole("link", { name: "Open in glossary" })).toHaveAttribute(
      "href", "#/glossary?term=brier-score");
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
    await waitFor(() => expect(trigger).toHaveFocus());
  });

  it("Space opens; Tab is trapped inside; related terms navigate within the dialog", async () => {
    const user = userEvent.setup();
    renderWithProvider(<Term id="ask">ask</Term>);
    screen.getByText("ask").focus();
    await user.keyboard(" ");
    const dialog = screen.getByRole("dialog", { name: "Ask" });
    for (let i = 0; i < 12; i++) await user.tab();
    expect(dialog.contains(document.activeElement)).toBe(true);
    await user.click(screen.getByRole("button", { name: "Bid" }));
    expect(screen.getByRole("dialog", { name: "Bid" })).toBeInTheDocument();
    const src = screen.getByRole("link", { name: "docs.kalshi.com" });
    expect(src).toHaveAttribute("rel", "noopener noreferrer");
  });

  it("clicking the backdrop closes the dialog", async () => {
    const user = userEvent.setup();
    renderWithProvider(<Term id="spread">spread</Term>);
    await user.click(screen.getByText("spread"));
    const backdrop = screen.getByRole("dialog").parentElement!;
    fireEvent.mouseDown(backdrop);
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});
