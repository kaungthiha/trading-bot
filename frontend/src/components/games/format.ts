/** Small display helpers for the Games page. */

export const cents = (p: number | null | undefined) => (p == null ? "—" : `${Math.round(p * 100)}¢`);
export const pct = (p: number | null | undefined, digits = 0) =>
  p == null ? "—" : `${(p * 100).toFixed(digits)}%`;

export function gameTime(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return new Intl.DateTimeFormat(undefined, { weekday: "short", hour: "numeric", minute: "2-digit" })
    .format(d);
}

export function ago(iso: string | null): string {
  if (!iso) return "never";
  const m = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (m < 1) return "just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.round(m / 60);
  return h < 48 ? `${h}h ago` : `${Math.round(h / 24)}d ago`;
}

/** ESPN's injury comment ("Curry (ankle) won't play Friday.") plus when it was posted. */
export function injuryWhy(detail: string | null | undefined, date?: string | null): string {
  const d = date && /^\d{4}-\d{2}-\d{2}$/.test(date) ? new Date(`${date}T12:00:00`) : null;
  const when = d && !Number.isNaN(d.getTime())
    ? `ESPN, ${new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" }).format(d)}` : "";
  return [detail?.trim(), when].filter(Boolean).join(" · ");
}

export const gameRef =(prefix: string, key: string) => `${prefix}-${key}`;
export function parseGameRef(ref: string | null): { prefix: string; key: string } | null {
  if (!ref) return null;
  const m = /^(KX[A-Z0-9]{2,20})-([A-Z0-9]{4,40})$/.exec(ref);
  return m ? { prefix: m[1]!, key: m[2]! } : null;
}
