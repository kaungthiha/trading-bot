/** Hairline navigation glyphs: 1.3px strokes in currentColor, decorative (the link text is
 * the accessible name). Hand-drawn paths, no icon library. */
export type GlyphName = "today" | "explore" | "terminal" | "games" | "markets" | "history" | "glossary";

const PATHS: Record<GlyphName, string> = {
  today: "M5 5.5h14a1 1 0 0 1 1 1v12a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1v-12a1 1 0 0 1 1-1zM4 9.5h16M8.5 3.5v4M15.5 3.5v4M8.5 14l2.2 2.2 4.8-4.7",
  explore: "M12 3.5a8.5 8.5 0 1 0 0 17a8.5 8.5 0 1 0 0-17zM15.6 8.4l-2.1 5.1-5.1 2.1 2.1-5.1zM12 3.5v1.6M12 18.9v1.6M3.5 12h1.6M18.9 12h1.6",
  terminal: "M4.5 5h15a1 1 0 0 1 1 1v11a1 1 0 0 1-1 1h-15a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1zM7.5 9.5l2.5 2-2.5 2M12.5 13.5h4M8 21h8",
  games: "M12 4a8 8 0 1 0 0 16a8 8 0 1 0 0-16zM4 12h16M12 4v16M6.6 6.2c2 1.6 3.2 3.6 3.2 5.8s-1.2 4.2-3.2 5.8M17.4 6.2c-2 1.6-3.2 3.6-3.2 5.8s1.2 4.2 3.2 5.8",
  markets: "M3.5 19.5h17M6 19V12M10 19V7M14 19v-5M18 19V9.5",
  history: "M6.5 3.5h11a1 1 0 0 1 1 1v15a1 1 0 0 1-1 1h-11a1 1 0 0 1-1-1v-15a1 1 0 0 1 1-1zM8.5 8h7M8.5 11.5h7M8.5 15h4",
  glossary: "M12 6.5C10 5 7.2 4.5 4 5v13c3.2-.5 6 0 8 1.5 2-1.5 4.8-2 8-1.5V5c-3.2-.5-6 0-8 1.5zM12 6.5V19.5",
};

export function Glyph({ name, size = 22 }: { name: GlyphName; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth={1.3} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"
      focusable="false">
      <path d={PATHS[name]} />
    </svg>
  );
}
