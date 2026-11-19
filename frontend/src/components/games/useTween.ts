import { useEffect, useRef, useState } from "react";

const reduced = () =>
  typeof window !== "undefined" && typeof window.matchMedia === "function"
  && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/** Animate a number toward `target` (ease-out, ~350ms). Jumps when motion is reduced. */
export function useTween(target: number | null, ms = 350): number | null {
  const [v, setV] = useState(target);
  const from = useRef(target);
  useEffect(() => {
    if (target == null || from.current == null || reduced() || typeof requestAnimationFrame === "undefined") {
      from.current = target;
      setV(target);
      return;
    }
    const start = performance.now();
    const a = from.current;
    let raf = 0;
    const step = (t: number) => {
      const k = Math.min(1, (t - start) / ms);
      const e = 1 - (1 - k) ** 3;
      const cur = a + (target - a) * e;
      from.current = cur;
      setV(cur);
      if (k < 1) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [target, ms]);
  return v;
}
