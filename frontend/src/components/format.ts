import type { DecimalString } from "../api/types";

/** Display an exact decimal price string as dollars without float conversion. */
export function formatPrice(p: DecimalString | null | undefined): string {
  return p == null ? "—" : `$${p}`;
}

export function formatAge(seconds: number): string {
  if (seconds < 0) return "future-dated";
  if (seconds < 60) return `${Math.round(seconds)}s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)}h`;
  return `${Math.round(seconds / 86400)}d`;
}

export function formatUtc(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toISOString().replace("T", " ").replace(/\.\d+Z$/, " UTC");
}
