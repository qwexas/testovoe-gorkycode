"use client";

import { useCallback, useEffect, useState } from "react";

import { type ApiError, apiErrorFromException } from "@/lib/api/errors";
import { moscowDateKey, moscowMidnight } from "@/lib/format";
import type { CalendarEvent } from "@/types/api";

import { fetchEvents } from "../api";

const REFRESH_MS = 60_000;

export type DayPlan =
  /** профиль ещё не готов: показывать нечего. */
  | { status: "idle" }
  | { status: "loading" }
  /** `error` — не удалось обновить, показаны прежние данные. */
  | { status: "ready"; events: CalendarEvent[]; error: ApiError | null }
  | { status: "failed"; error: ApiError };

type Loaded = { key: string; events: CalendarEvent[] | null; error: ApiError | null };

/**
 * план на сегодня и завтра по Москве: GET /api/events за [сегодня 00:00, послезавтра 00:00).
 * Обновляется раз в минуту (пока вкладка видна), при смене дня, профиля и по `refresh()` —
 * после ответов ассистента, которые меняли записи.
 */
export function useDayPlan(
  profileId: string | null,
  now: Date | null,
): { plan: DayPlan; refresh: () => void } {
  const dayKey = now ? moscowDateKey(now) : null;
  const key = profileId && dayKey ? `${profileId}:${dayKey}` : null;
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [version, setVersion] = useState(0);

  useEffect(() => {
    if (!key || !dayKey) return undefined;
    const controller = new AbortController();
    fetchEvents(
      { from: moscowMidnight(dayKey), to: moscowMidnight(dayKey, 2) },
      controller.signal,
    ).then(
      (events) => setLoaded({ key, events, error: null }),
      (cause: unknown) => {
        if (controller.signal.aborted) return;
        const error = apiErrorFromException(cause);
        // неудачное фоновое обновление не стирает уже показанный план.
        setLoaded((previous) => ({
          key,
          events: previous?.key === key ? previous.events : null,
          error,
        }));
      },
    );
    return () => controller.abort();
  }, [key, dayKey, version]);

  useEffect(() => {
    if (!key) return undefined;
    const refreshIfVisible = () => {
      if (document.visibilityState === "visible") setVersion((value) => value + 1);
    };
    const interval = window.setInterval(refreshIfVisible, REFRESH_MS);
    document.addEventListener("visibilitychange", refreshIfVisible);
    window.addEventListener("online", refreshIfVisible);
    return () => {
      window.clearInterval(interval);
      document.removeEventListener("visibilitychange", refreshIfVisible);
      window.removeEventListener("online", refreshIfVisible);
    };
  }, [key]);

  const refresh = useCallback(() => setVersion((value) => value + 1), []);

  let plan: DayPlan;
  if (!key) plan = { status: "idle" };
  else if (loaded?.key !== key) plan = { status: "loading" };
  else if (loaded.events) plan = { status: "ready", events: loaded.events, error: loaded.error };
  else plan = { status: "failed", error: loaded.error ?? apiErrorFromException(null) };

  return { plan, refresh };
}
