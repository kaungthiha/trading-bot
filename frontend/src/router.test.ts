import { describe, expect, it } from "vitest";

import { href, parseHash, sectionOf } from "./router";

describe("parseHash", () => {
  it("lands on Today for the root and anything unknown", () => {
    for (const h of ["", "#", "#/", "#/today", "#/nope", "#/games?game=<script>"]) {
      expect(parseHash(h).page, h).toBe("today"); // a malformed game ref is not a games link
    }
  });

  it("keeps every pre-Phase-2 deep link working", () => {
    expect(parseHash("#/history").page).toBe("journal");
    expect(parseHash("#/glossary?term=fair-price")).toMatchObject({ page: "learn", term: "fair-price" });
    expect(parseHash("#/games?game=KXNBA-26NOV19GSWMEM")).toMatchObject({ page: "games", game: "KXNBA-26NOV19GSWMEM" });
    expect(parseHash("#/markets?event=KXCPI-26DEC")).toMatchObject({ page: "markets", event: "KXCPI-26DEC" });
    expect(parseHash("#/terminal")).toMatchObject({ page: "tools", tab: null });
  });

  it("accepts the new names and validates tabs", () => {
    expect(parseHash("#/journal").page).toBe("journal");
    expect(parseHash("#/learn?term=spread")).toMatchObject({ page: "learn", term: "spread" });
    expect(parseHash("#/explore").page).toBe("games");
    expect(parseHash("#/terminal?tab=signals").tab).toBe("signals");
    expect(parseHash("#/terminal?tab=hacker").tab).toBeNull();
  });

  it("maps pages to rail sections", () => {
    expect(sectionOf("games")).toBe("explore");
    expect(sectionOf("markets")).toBe("explore");
    expect(sectionOf("tools")).toBe("tools");
  });
});

describe("href builders", () => {
  it("round-trip through the parser and refuse bad input", () => {
    expect(parseHash(href.game("KXNBA-26NOV19GSWMEM")).game).toBe("KXNBA-26NOV19GSWMEM");
    expect(href.game("javascript:alert(1)")).toBe("#/games");
    expect(parseHash(href.market("KX.A-B_1")).event).toBe("KX.A-B_1");
    expect(href.market("../x")).toBe("#/markets");
    expect(parseHash(href.tools("paper")).tab).toBe("paper");
    expect(href.learn("Bad Term")).toBe("#/glossary");
  });
});
