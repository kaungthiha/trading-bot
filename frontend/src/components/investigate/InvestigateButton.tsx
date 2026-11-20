import type { ComboLeg, LegEvidence } from "../../api/types";
import { Tip } from "../design/Tip";
import { useScanTime } from "../docket/scanTime";
import { buildHypothesis, supportFor } from "./hypothesis";
import { investigation } from "./store";

/** Entry point for one exact selection. On the Docket (your selections) an unsupported market
 * explains why; on browsing surfaces (`quiet`) unsupported markets simply get no button, so a
 * page of CPI or election markets isn't littered with notes. */
export function InvestigateButton({ leg, ev, scanAt, quiet = false }: {
  leg: ComboLeg; ev?: LegEvidence; scanAt?: string | null; quiet?: boolean }) {
  const scan = useScanTime();
  const s = supportFor(leg);
  if (!s.ok) return quiet ? null : <Tip text={s.reason} className="inv-unsupported">can't investigate</Tip>;
  return (
    <button type="button" className="inv-trigger" aria-label={`Investigate ${leg.side.toUpperCase()}: ${leg.label}`}
      onClick={(e) => investigation.open(buildHypothesis(leg, ev, scanAt ?? scan ?? null), e.currentTarget)}>
      Investigate
    </button>
  );
}
