import { useCallback, useState } from "react";

import "./games.css";

import { ControlBar } from "../ControlBar";
import { ErrorBoundary } from "../ErrorBoundary";
import { PageHead } from "../Hairline";
import { useDataRefresh } from "../useDataRefresh";
import { parseGameRef } from "./format";
import { GameBoard } from "./GameBoard";
import { GameList } from "./GameList";
import { SlatePanel } from "./SlatePanel";

interface Props {
  gameRef: string | null;
  onOpenGame: (ref: string | null) => void;
}

/** Pick a game, tap prices into one slip, and see the combo priced and checked. */
export function GamesPage({ gameRef, onOpenGame }: Props) {
  const [tick, setTick] = useState(0);
  useDataRefresh(useCallback(() => setTick((t) => t + 1), []));
  const g = parseGameRef(gameRef);
  return (
    <div className="games-page">
      <PageHead figure="riffle" title="Games" actions={<ControlBar compact />}>
        One game per screen. Tap prices onto the docket; it prices the combo and checks each leg.
      </PageHead>
      <div className="games-layout">
        <GameList selected={gameRef} onSelect={onOpenGame} tick={tick} />
        <ErrorBoundary resetKey={gameRef ?? ""}>
          {g ? <GameBoard prefix={g.prefix} gameKey={g.key} tick={tick} />
            : <div className="board"><SlatePanel prefix="KXNBA" /></div>}
        </ErrorBoundary>
      </div>
    </div>
  );
}
