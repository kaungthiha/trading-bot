import { useEffect, useState } from "react";

export type Density = "comfortable" | "compact";
const KEY = "krt.density";

function initial(): Density {
  try {
    return localStorage.getItem(KEY) === "compact" ? "compact" : "comfortable";
  } catch {
    return "comfortable"; // storage blocked: fall back silently
  }
}

/** Row density, stored locally (a display preference, nothing sensitive). Applied as
 * data-density on <html>, which styles/tokens.css reads. */
export function useDensity(): [Density, (d: Density) => void] {
  const [density, setDensity] = useState<Density>(initial);
  useEffect(() => {
    document.documentElement.dataset.density = density;
    try { localStorage.setItem(KEY, density); } catch { /* ignore */ }
  }, [density]);
  return [density, setDensity];
}
