"use client";

import { useEffect, useState } from "react";

/**
 * Монотонные часы для коротких отсчётов (окно отмены, длительность записи):
 * тикают с шагом `intervalMs`, только пока `active`. Значение — performance.now().
 */
export function useTicker(active: boolean, intervalMs = 250): number {
  const [now, setNow] = useState(() =>
    typeof performance === "undefined" ? 0 : performance.now(),
  );

  useEffect(() => {
    if (!active) return undefined;
    // Первый тик сразу: отсчёт не должен показывать устаревшее значение.
    const first = window.setTimeout(() => setNow(performance.now()), 0);
    const interval = window.setInterval(() => setNow(performance.now()), intervalMs);
    return () => {
      window.clearTimeout(first);
      window.clearInterval(interval);
    };
  }, [active, intervalMs]);

  return now;
}
