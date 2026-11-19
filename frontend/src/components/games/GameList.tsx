import { useEffect, useMemo, useState } from "react";

import { api, ApiError } from "../../api/client";
import type { GameList as GameListT } from "../../api/types";
import { gameRef, gameTime, pct } from "./format";

interface Props {
  selected: string | null;
  onSelect: (ref: string) => void;
  tick: number;
}

/** Upcoming games, one league at a time. */
export function GameList({ selected, onSelect, tick }: Props) {
  const [data, setData] = useState<GameListT | null>(null);
  const [league, setLeague] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    api.games().then((d) => { setData(d); setErr(null); },
      (e) => setErr(e instanceof ApiError ? e.message : "Backend unreachable"));
  }, [tick]);

  const leagues = data?.leagues ?? [];
  const active = league ?? (leagues.some((l) => l.league === "NBA") ? "NBA" : leagues[0]?.league ?? null);
  const items = useMemo(() => (data?.items ?? []).filter((g) => g.league === active
    && (!q || `${g.title} ${g.sub_title}`.toLowerCase().includes(q.toLowerCase()))), [data, active, q]);

  return (
    <nav className="game-list" aria-label="Games">
      <div className="league-chips" role="group" aria-label="League">
        {leagues.slice(0, 10).map((l) => (
          <button key={l.league} type="button" className="pill" aria-pressed={l.league === active}
            onClick={() => setLeague(l.league)}>{l.league}</button>
        ))}
      </div>
      <input type="search" aria-label="Find a game" placeholder="Team…" value={q} maxLength={60}
        onChange={(e) => setQ(e.target.value)} />
      {err && <p role="alert" className="small">{err}</p>}
      {data && items.length === 0 && <p className="small muted">No upcoming games here. Run a scan.</p>}
      <ul>
        {items.map((g) => {
          const ref = gameRef(g.prefix, g.game_key);
          const [a, b] = g.teams;
          return (
            <li key={ref}>
              <button type="button" className="game-card" aria-pressed={selected === ref}
                onClick={() => onSelect(ref)}>
                <span className="game-card-top">
                  <strong>{a?.code ?? "?"} @ {b?.code ?? "?"}</strong>
                  <span className="muted small">{gameTime(g.occurs_at)}</span>
                </span>
                {a && b && a.win != null && b.win != null && (
                  <span className="winbar mini" aria-label={`${a.code} ${pct(a.win)}, ${b.code} ${pct(b.win)}`}>
                    <span className="seg a" style={{ flexGrow: a.win }} />
                    <span className="seg b" style={{ flexGrow: b.win }} />
                  </span>
                )}
                <span className="muted small">{g.markets.toLocaleString()} markets</span>
              </button>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
