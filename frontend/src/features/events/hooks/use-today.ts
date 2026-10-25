"use client";

import { useSyncExternalStore } from "react";

import { TIME_ZONE, formatDay } from "@/lib/format";

const isoDateFormatter = new Intl.DateTimeFormat("en-CA", {
  timeZone: TIME_ZONE,
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
});

const CHECK_INTERVAL_MS = 60_000;

function getTodayIso(): string {
  return isoDateFormatter.format(new Date());
}

function getServerToday(): null {
  return null;
}

function subscribe(onChange: () => void): () => void {
  const interval = window.setInterval(onChange, CHECK_INTERVAL_MS);
  return () => window.clearInterval(interval);
}

/**
 * Сегодняшняя дата по Москве. На сервере (и при пререндере) — null: дата зависит от
 * момента открытия, а не от момента сборки. Обновляется после полуночи.
 */
export function useToday(): { iso: string; label: string } | null {
  const iso = useSyncExternalStore(subscribe, getTodayIso, getServerToday);
  if (iso === null) return null;
  // Полдень по Москве: тот же календарный день при любом часовом поясе браузера.
  return { iso, label: formatDay(new Date(`${iso}T12:00:00+03:00`)) };
}
