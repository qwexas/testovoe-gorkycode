"use client";

import { type RefObject, useEffect, useRef } from "react";

/**
 * Привязывает уровень голоса к DOM-элементу без перерисовки React: `apply` вызывается
 * на каждом кадре, пока `active`. Индикатор уровня — обратная связь на запись,
 * поэтому он работает и при reduced motion, но реже (10 кадров в секунду).
 */
export function useLevelMeter<T extends HTMLElement>(
  levelRef: RefObject<number>,
  active: boolean,
  apply: (element: T, level: number) => void,
): RefObject<T | null> {
  const elementRef = useRef<T | null>(null);
  const applyRef = useRef(apply);

  useEffect(() => {
    applyRef.current = apply;
  });

  useEffect(() => {
    const element = elementRef.current;
    if (!element) return undefined;
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const interval = reduced ? 100 : 0;
    let frame = 0;
    let last = 0;

    const tick = (now: number) => {
      if (now - last >= interval) {
        last = now;
        applyRef.current(element, levelRef.current ?? 0);
      }
      frame = requestAnimationFrame(tick);
    };

    if (active) {
      frame = requestAnimationFrame(tick);
    } else {
      applyRef.current(element, 0);
    }
    return () => cancelAnimationFrame(frame);
  }, [active, levelRef]);

  return elementRef;
}
