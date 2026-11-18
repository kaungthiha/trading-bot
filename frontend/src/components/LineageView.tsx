import { useState } from "react";

import { api, ApiError } from "../api/client";
import type { SignalLineage } from "../api/types";
import { formatUtc } from "./format";

/** On-demand trace: signal <- quote <- ingestion run; rules; mapping; model run <- evidence. */
export function LineageView({ signalId }: { signalId: string }) {
  const [data, setData] = useState<SignalLineage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);

  function toggle() {
    const next = !open;
    setOpen(next);
    if (next && !data) {
      api.signalLineage(signalId).then(setData, (e) =>
        setError(e instanceof ApiError ? e.message : "Lineage unavailable"));
    }
  }

  return (
    <div className="lineage small">
      <button type="button" className="link-button" aria-expanded={open} onClick={toggle}>
        {open ? "Hide lineage" : "Trace lineage"}
      </button>
      {open && error && <p role="alert">{error}</p>}
      {open && data && (
        <ol className="lineage-steps">
          <li>
            <strong>Quote</strong>{" "}
            {data.quote ? (
              <>
                observed {formatUtc(data.quote.observed_at)} · YES bid {data.quote.yes_bid ?? "—"} /
                ask {data.quote.yes_ask_derived ?? "—"} (derived) · via{" "}
                {data.quote.ingestion_run
                  ? `${data.quote.ingestion_run.adapter} run ${data.quote.ingestion_run.id.slice(0, 8)}`
                  : "unknown run"}
              </>
            ) : "none"}
          </li>
          <li>
            <strong>Rules</strong>{" "}
            {data.rules ? (
              <>hash {data.rules.hash.slice(0, 12)}… {data.rules.is_current ? "(current)" : "(CHANGED since)"}</>
            ) : "none"}
          </li>
          <li>
            <strong>Mapping</strong>{" "}
            {data.mapping ? `${data.mapping.status} by ${data.mapping.actor} → ${data.mapping.reference_month} > ${data.mapping.threshold}%` : "none"}
          </li>
          <li>
            <strong>Model run</strong>{" "}
            {data.model_run ? (
              <>
                {data.model_run.model} v{data.model_run.version} as of {formatUtc(data.model_run.as_of)}
                {" · "}p={data.model_run.p_yes?.toFixed(3) ?? "—"}
              </>
            ) : "none"}
          </li>
          <li>
            <strong>Evidence</strong> {data.evidence.length} vintages
            {data.evidence.length > 0 && (
              <> ({data.evidence[0]!.observation_date.slice(0, 7)} … {data.evidence[data.evidence.length - 1]!.observation_date.slice(0, 7)})</>
            )}{" "}
            · leakage check:{" "}
            <span className={`badge ${data.leakage_check === "pass" ? "paper" : "stale"}`}>
              {data.leakage_check}
            </span>
          </li>
          <li>
            <strong>Fees</strong>{" "}
            {data.fee_schedule ? `${data.fee_schedule.version} (${data.fee_schedule.verified ? "verified" : "UNVERIFIED"})` : "schedule not in current file"}
          </li>
        </ol>
      )}
    </div>
  );
}
