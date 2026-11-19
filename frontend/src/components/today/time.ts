/** "12m ago", "in 3h", "in 2d". Coarse on purpose: exact times are in the title attribute. */
export function rel(iso: string | null | undefined, now: number): string {
  if (!iso) return "—";
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return "—";
  const s = Math.round((t - now) / 1000);
  const a = Math.abs(s);
  const v = a < 60 ? null : a < 3600 ? `${Math.round(a / 60)}m` : a < 172800 ? `${Math.round(a / 3600)}h`
    : `${Math.round(a / 86400)}d`;
  if (v === null) return "just now";
  return s < 0 ? `${v} ago` : `in ${v}`;
}

export function exact(iso: string | null | undefined): string | undefined {
  if (!iso) return undefined;
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? undefined : d.toLocaleString();
}
