import { href } from "../../router";

/** Explore = one place to browse: games (one game per screen) or every Kalshi market.
 * Both keep their own URLs, so deep links and back/forward behave as before. */
export function ExploreSwitch({ page }: { page: "games" | "markets" }) {
  return (
    <nav aria-label="Explore" className="explore-switch">
      <a href={href.game()} aria-current={page === "games" ? "page" : undefined}>Games</a>
      <a href={href.market()} aria-current={page === "markets" ? "page" : undefined}>All markets</a>
    </nav>
  );
}
