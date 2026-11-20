import { useEffect, useMemo, useState } from "react";

import { api, ApiError } from "../../api/client";
import type { GameChip, GameDetail, GameGroup, GameInjuries, GamePlayer } from "../../api/types";
import { ago, cents, gameTime, pct } from "./format";
import { IdeasPanel } from "./IdeasPanel";
import { slip, useSlip } from "./slip";
import { Tip } from "../design/Tip";

const NEAR = 7; // ladder chips shown before "show all"

function nearest(chips: GameChip[], n: number): GameChip[] {
  if (chips.length <= n) return chips;
  const scored = chips.map((c, i) => ({ i, d: c.implied == null ? 9 : Math.abs(c.implied - 0.5) }));
  const keep = new Set(scored.sort((x, y) => x.d - y.d).slice(0, n).map((s) => s.i));
  return chips.filter((_, i) => keep.has(i));
}

function Chip({ c, event, eligible, inSlip, longLabel }: {
  c: GameChip; event: string; eligible: boolean; inSlip: boolean; longLabel: string }) {
  const p = c.implied;
  return (
    <button type="button" className="chip" aria-pressed={inSlip}
      title={`${c.title} · YES ${cents(c.yes_ask)} / NO ${cents(c.no_ask)}${eligible ? "" : " · not combinable on Kalshi"}`}
      aria-label={`${inSlip ? "Remove" : "Add"} ${longLabel}, ${pct(p)}`}
      onClick={() => slip.toggle({ ticker: c.ticker, side: "yes", label: longLabel, event })}>
      <span className="chip-label">{c.label}</span>
      <span className="chip-price">{pct(p)}</span>
      <span className="chip-bar" style={{ transform: `scaleX(${p ?? 0})` }} />
      {!eligible && <span className="chip-flag" aria-hidden="true">•</span>}
    </button>
  );
}

function ChipRail({ group, tickers }: { group: GameGroup; tickers: Set<string> }) {
  const [all, setAll] = useState(false);
  const shown = all || group.kind === "pick" ? group.markets : nearest(group.markets, NEAR);
  const hidden = group.markets.length - shown.length;
  return (
    <div className="rail-row">
      <div className="rail-head">
        <span className="rail-title">{group.label}</span>
        {group.median_label && <Tip text="Where the market's prices put the 50/50 point" className="median-badge">
          mkt {group.median_label}</Tip>}
      </div>
      <div className="rail">
        {shown.map((c) => (
          <Chip key={c.ticker} c={c} event={group.event_ticker} eligible={group.eligible}
            inSlip={tickers.has(c.ticker)} longLabel={c.title} />
        ))}
        {group.markets.length > NEAR && group.kind === "ladder" && (
          <button type="button" className="chip more" onClick={() => setAll(!all)}>
            {all ? "fewer" : `+${hidden}`}
          </button>
        )}
      </div>
    </div>
  );
}

function PlayerGrid({ game, tickers }: { game: GameDetail; tickers: Set<string> }) {
  const [q, setQ] = useState("");
  const [team, setTeam] = useState<string | null>(null);
  const [open, setOpen] = useState<{ player: string; stat: string } | null>(null);
  const players = game.players.filter((p) => (!team || p.team === team)
    && (!q || p.name.toLowerCase().includes(q.toLowerCase())));
  const cell = (p: GamePlayer, stat: string) => {
    const g = p.stats[stat];
    if (!g) return <td key={stat} className="muted">·</td>;
    const picked = g.markets.some((m) => tickers.has(m.ticker));
    const isOpen = open?.player === p.id && open.stat === stat;
    const yes = g.markets[0]?.implied;
    return (
      <td key={stat}>
        <button type="button" className={`cell${picked ? " picked" : ""}`} aria-expanded={isOpen}
          aria-label={`${p.name} ${game.stat_labels[stat]}: ${g.median != null ? `market line ${g.median.toFixed(1)}` : pct(yes)}`}
          onClick={() => setOpen(isOpen ? null : { player: p.id, stat })}>
          {g.median != null ? g.median.toFixed(1) : pct(yes)}
        </button>
      </td>
    );
  };
  return (
    <div className="player-grid">
      <div className="grid-tools">
        <input type="search" aria-label="Find a player" placeholder="Player…" value={q} maxLength={60}
          onChange={(e) => setQ(e.target.value)} />
        <div role="group" aria-label="Team">
          <button type="button" className="pill" aria-pressed={!team} onClick={() => setTeam(null)}>Both</button>
          {game.teams.map((t) => (
            <button key={t.code} type="button" className="pill" aria-pressed={team === t.code}
              onClick={() => setTeam(t.code)}>{t.code}</button>
          ))}
        </div>
        <Tip text="The number in each cell is where the market's prices cross 50%: its median for that stat." className="small muted">
          cell = market's median line
        </Tip>
      </div>
      <div className="grid-scroll">
        <table>
          <thead>
            <tr><th scope="col">Player</th>{game.stats.map((s) => <th key={s} scope="col">{game.stat_labels[s]}</th>)}</tr>
          </thead>
          <tbody>
            {players.map((p) => {
              const g = open?.player === p.id ? p.stats[open.stat] : undefined;
              return [
                <tr key={p.id}>
                  <th scope="row">{p.name} <span className="muted small">{p.team}</span></th>
                  {game.stats.map((s) => cell(p, s))}
                </tr>,
                g && open && (
                  <tr key={`${p.id}-open`} className="expand-row">
                    <td colSpan={game.stats.length + 1}>
                      <div className="rail">
                        {g.markets.map((c) => (
                          <Chip key={c.ticker} c={c} event={g.event_ticker} eligible={g.eligible}
                            inSlip={tickers.has(c.ticker)} longLabel={c.title} />
                        ))}
                      </div>
                    </td>
                  </tr>
                ),
              ];
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function InjuryStrip({ game }: { game: GameDetail }) {
  const [inj, setInj] = useState<GameInjuries | null>(null);
  useEffect(() => {
    setInj(null);
    if (!game.evidence_supported) return;
    api.gameInjuries(game.prefix, game.game_key).then(setInj, () => setInj(null));
  }, [game.prefix, game.game_key, game.evidence_supported]);
  const items = inj?.teams.flatMap((t) => t.items.map((i) => ({ ...i, code: t.code }))) ?? [];
  if (!inj) return null;
  return (
    <div className="injury-strip" aria-label="Injury report (ESPN)">
      {items.length === 0 ? <span className="small muted">No injuries listed</span> : items.map((i) => (
        <span key={`${i.code}-${i.player}`} className={`inj ${/out/i.test(i.status) ? "out" : ""}`}>
          {i.code} · {i.player} <em>{i.status}</em>
        </span>
      ))}
    </div>
  );
}

interface Props { prefix: string; gameKey: string; tick: number }

export function GameBoard({ prefix, gameKey, tick }: Props) {
  const [game, setGame] = useState<GameDetail | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [tab, setTab] = useState("main");
  const [prot, setProt] = useState(false);
  const legs = useSlip();
  const tickers = useMemo(() => new Set(legs.map((l) => l.ticker)), [legs]);

  useEffect(() => {
    let cancel = false;
    api.game(prefix, gameKey, prot).then((g) => { if (!cancel) { setGame(g); setErr(null); } },
      (e) => { if (!cancel) setErr(e instanceof ApiError ? e.message : "Backend unreachable"); });
    return () => { cancel = true; };
  }, [prefix, gameKey, prot, tick]);

  useEffect(() => { setTab("main"); }, [prefix, gameKey]);

  if (err) return <p role="alert">{err}</p>;
  if (!game || game.game_key !== gameKey) return <div className="board skeleton" aria-busy="true" />;
  const [a, b] = game.teams;
  const tabs = [...game.sections.filter((s) => s.id === "main"),
    ...(game.players.length ? [{ id: "players", label: `Players (${game.players.length})`, groups: [] }] : []),
    ...game.sections.filter((s) => s.id !== "main"),
    ...(game.evidence_supported ? [{ id: "ideas", label: "Ideas", groups: [] }] : [])];
  const current = tabs.find((t) => t.id === tab) ?? tabs[0];
  return (
    <section className="board" aria-labelledby="board-h">
      <header className="board-head">
        <div>
          <h2 id="board-h">{a?.name} <span className="muted">@</span> {b?.name}</h2>
          <span className="small muted">{gameTime(game.occurs_at)} · prices {ago(game.refreshed_at)}</span>
        </div>
        {a && b && a.win != null && b.win != null && (
          <div className="winbar big" role="img" aria-label={`Win chance: ${a.code} ${pct(a.win)}, ${b.code} ${pct(b.win)}`}>
            <span className="seg a" style={{ flexGrow: a.win }}><b>{a.code}</b> {pct(a.win)}</span>
            <span className="seg b" style={{ flexGrow: b.win }}>{pct(b.win)} <b>{b.code}</b></span>
          </div>
        )}
      </header>
      <InjuryStrip game={game} />
      <div className="tabs" role="tablist" aria-label="Market groups">
        {tabs.map((t) => (
          <button key={t.id} type="button" role="tab" aria-selected={current?.id === t.id}
            onClick={() => setTab(t.id)}>{t.label}</button>
        ))}
        {game.protected_available && tab === "players" && (
          <span className="small protected-toggle">
            <label><input type="checkbox" checked={prot} onChange={(e) => setProt(e.target.checked)} /> Protected</label>{" "}
            <Tip text="Kalshi also lists 'Protected' versions of player props: separate markets with their own rules and prices.">what's this?</Tip>
          </span>
        )}
      </div>
      <div className="tab-panel" role="tabpanel" key={current?.id}>
        {current?.id === "ideas" ? <IdeasPanel prefix={prefix} gameKey={gameKey} />
          : current?.id === "players"
          ? <PlayerGrid game={game} tickers={tickers} />
          : current?.groups.map((g) => <ChipRail key={g.id} group={g} tickers={tickers} />)}
      </div>
      <p className="small muted legend-line">Tap a price to add YES to the docket (flip to NO there). <span className="chip-flag">•</span> = can't be combined on Kalshi.</p>
    </section>
  );
}
