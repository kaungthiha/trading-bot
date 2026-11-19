import { useEffect, useSyncExternalStore } from "react";

import { api } from "../../api/client";

/** When the full Kalshi catalog (every price on Explore, Today and the Docket) was last
 * scanned. One fetch shared by every reader; refetched when a background job finishes.
 * undefined = unknown (not loaded / backend down), null = never scanned. */
let value: string | null | undefined = undefined;
let inflight = false;
const subs = new Set<() => void>();
const EVENT = "krt:data-updated"; // same event useDataRefresh listens to

export function refreshScanTime(): void {
  if (inflight) return;
  inflight = true;
  api.catalogStatus().then(
    (s) => { value = s.refreshed_at; },
    () => { value = undefined; },
  ).finally(() => { inflight = false; subs.forEach((f) => f()); });
}

function subscribe(f: () => void) {
  subs.add(f);
  if (subs.size === 1) {
    window.addEventListener(EVENT, refreshScanTime);
  }
  return () => {
    subs.delete(f);
    if (subs.size === 0) window.removeEventListener(EVENT, refreshScanTime);
  };
}

export function useScanTime(): string | null | undefined {
  const v = useSyncExternalStore(subscribe, () => value, () => value);
  useEffect(() => { if (value === undefined) refreshScanTime(); }, []);
  return v;
}

/** Test helper. */
export function resetScanTime(): void { value = undefined; inflight = false; }
