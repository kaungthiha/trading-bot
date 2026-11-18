import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { TERMS } from "../glossary/terms";
import { Term } from "./Term";

describe("<Term>", () => {
  it("shows a non-interactive tooltip on focus and hides it on Escape, keeping focus", async () => {
    const user = userEvent.setup();
    render(<Term id="spread">spread</Term>);
    const trigger = screen.getByText("spread");

    await user.tab();
    expect(trigger).toHaveFocus();
    const tip = screen.getByRole("tooltip");
    expect(tip).toHaveTextContent(TERMS.spread.shortDefinition);
    expect(trigger).toHaveAttribute("aria-describedby", tip.id);
    expect(tip.querySelector("a, button")).toBeNull();

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("tooltip")).toBeNull();
    expect(trigger).toHaveFocus();
  });

  it("shows on hover and hides on mouse leave", async () => {
    const user = userEvent.setup();
    render(<Term id="bid">bid</Term>);
    await user.hover(screen.getByText("bid"));
    expect(screen.getByRole("tooltip")).toBeInTheDocument();
    await user.unhover(screen.getByText("bid"));
    expect(screen.queryByRole("tooltip")).toBeNull();
  });
});
