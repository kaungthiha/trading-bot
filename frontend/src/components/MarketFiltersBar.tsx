import { useEffect, useState } from "react";

import { MARKET_STATUSES, type MarketFilters, type MarketStatus } from "../api/types";

interface Props {
  categories: string[];
  value: MarketFilters;
  onChange: (next: MarketFilters) => void;
  debounceMs?: number;
}

export function MarketFiltersBar({ categories, value, onChange, debounceMs = 250 }: Props) {
  const [q, setQ] = useState(value.q ?? "");

  // Debounce free-text search so typing doesn't fire a request per keystroke.
  useEffect(() => {
    if (q === (value.q ?? "")) return;
    const t = setTimeout(() => onChange({ ...value, q: q || undefined }), debounceMs);
    return () => clearTimeout(t);
  }, [q, value, onChange, debounceMs]);

  return (
    <form className="filters" role="search" onSubmit={(e) => e.preventDefault()}>
      <label>
        Search
        <input
          type="search"
          value={q}
          maxLength={100}
          placeholder="title or ticker"
          onChange={(e) => setQ(e.target.value)}
        />
      </label>
      <label>
        Category
        <select
          value={value.category ?? ""}
          onChange={(e) => onChange({ ...value, category: e.target.value || undefined })}
        >
          <option value="">All</option>
          {categories.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
      </label>
      <label>
        Status
        <select
          value={value.status ?? ""}
          onChange={(e) =>
            onChange({ ...value, status: (e.target.value || undefined) as MarketStatus | undefined })
          }
        >
          <option value="">All</option>
          {MARKET_STATUSES.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
      </label>
    </form>
  );
}
