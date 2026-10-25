"use client";

import { type RefObject, useEffect, useRef } from "react";

/** Прокручивает историю к последней реплике, когда она меняется; при открытии — сразу. */
export function useScrollToLatest<T extends HTMLElement>(key: unknown): RefObject<T | null> {
  const ref = useRef<T | null>(null);
  const firstRun = useRef(true);

  useEffect(() => {
    const element = ref.current;
    if (!element) return;
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const behavior = firstRun.current || reduced ? "auto" : "smooth";
    firstRun.current = false;
    element.scrollTo({ top: element.scrollHeight, behavior });
  }, [key]);

  return ref;
}
