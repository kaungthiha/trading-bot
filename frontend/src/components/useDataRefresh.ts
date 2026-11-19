import { useEffect } from "react";

const EVENT = "krt:data-updated";

/** Tell every panel that background jobs changed the data. */
export function announceDataUpdated(): void {
  window.dispatchEvent(new CustomEvent(EVENT));
}

/** Re-run `refresh` whenever a background job finishes. */
export function useDataRefresh(refresh: () => void): void {
  useEffect(() => {
    window.addEventListener(EVENT, refresh);
    return () => window.removeEventListener(EVENT, refresh);
  }, [refresh]);
}
