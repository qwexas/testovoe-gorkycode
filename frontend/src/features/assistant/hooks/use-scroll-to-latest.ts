"use client";

import { type RefObject, useEffect, useRef } from "react";

const TOP_GAP_PX = 16;

/**
 * Прокручивает лог к последней реплике, когда она меняется; при загрузке истории — сразу.
 * Длинный ответ (таблица за неделю) не прокручивается до конца: виден вопрос
 * пользователя и начало ответа. Реплики помечены `data-log-entry` и `data-role`.
 */
export function useScrollToLatest<T extends HTMLElement>(
  key: unknown,
  /** Смена значения — лог снова показан (вкладка на телефоне): прокрутить без анимации. */
  visibilityKey?: unknown,
): RefObject<T | null> {
  const ref = useRef<T | null>(null);
  const shownEntries = useRef(0);
  const shownFor = useRef(visibilityKey);

  useEffect(() => {
    const element = ref.current;
    if (!element) return;
    const entries = element.querySelectorAll<HTMLElement>("[data-log-entry]");
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    // История пришла впервые — сразу в конец, без долгой прокрутки через весь лог.
    const instant = shownEntries.current === 0 || shownFor.current !== visibilityKey;
    const behavior = instant || reduced ? "auto" : "smooth";
    shownEntries.current = entries.length;
    shownFor.current = visibilityKey;

    const last = entries[entries.length - 1];
    const previous = entries[entries.length - 2];
    const anchor =
      previous?.dataset.role === "user" && last?.dataset.role !== "user" ? previous : last;
    let top = element.scrollHeight;
    if (anchor) {
      const anchorTop = anchor.offsetTop - TOP_GAP_PX;
      if (element.scrollHeight - anchorTop > element.clientHeight) top = anchorTop;
    }
    element.scrollTo({ top, behavior });
  }, [key, visibilityKey]);

  return ref;
}
