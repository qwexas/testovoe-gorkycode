/** Форматирование событий для вариантов. Язык и часовой пояс фиксированы (решение Q9). */
import { LOCALE, TIME_ZONE, formatCount } from "@/lib/format";

import { DEMO_NOW } from "./mock-data";
import type { CalendarEvent } from "./types";

const timeFormatter = new Intl.DateTimeFormat(LOCALE, {
  timeZone: TIME_ZONE,
  hour: "2-digit",
  minute: "2-digit",
});

const dayMonthFormatter = new Intl.DateTimeFormat(LOCALE, {
  timeZone: TIME_ZONE,
  day: "numeric",
  month: "long",
});

const weekdayFormatter = new Intl.DateTimeFormat(LOCALE, {
  timeZone: TIME_ZONE,
  weekday: "long",
});

const shortWeekdayFormatter = new Intl.DateTimeFormat(LOCALE, {
  timeZone: TIME_ZONE,
  weekday: "short",
});

const fullDateFormatter = new Intl.DateTimeFormat(LOCALE, {
  timeZone: TIME_ZONE,
  day: "numeric",
  month: "long",
  year: "numeric",
});

const numericDateFormatter = new Intl.DateTimeFormat(LOCALE, {
  timeZone: TIME_ZONE,
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
});

const isoDayFormatter = new Intl.DateTimeFormat("en-CA", {
  timeZone: TIME_ZONE,
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
});

const DAY_MS = 86_400_000;

export const TYPE_LABELS: Record<CalendarEvent["type"], string> = {
  task: "задача",
  reminder: "напоминание",
  meeting: "встреча",
};

/** «17:00» */
export function formatTime(iso: string): string {
  return timeFormatter.format(new Date(iso));
}

/** «2026-10-25» по Москве */
export function isoDay(value: string | Date): string {
  return isoDayFormatter.format(typeof value === "string" ? new Date(value) : value);
}

/** Сдвиг в днях относительно «сегодня» демо: 0 — сегодня, 1 — завтра. */
export function dayOffset(iso: string): number {
  const target = Date.parse(`${isoDay(iso)}T12:00:00+03:00`);
  const today = Date.parse(`${isoDay(DEMO_NOW)}T12:00:00+03:00`);
  return Math.round((target - today) / DAY_MS);
}

/** «сегодня», «завтра», «вторник, 27 октября», «14 апреля 2024» */
export function formatDayLabel(iso: string): string {
  const offset = dayOffset(iso);
  const date = new Date(iso);
  if (offset === 0) return "сегодня";
  if (offset === 1) return "завтра";
  if (offset === -1) return "вчера";
  if (date.getFullYear() !== DEMO_NOW.getFullYear()) return fullDateFormatter.format(date);
  return `${weekdayFormatter.format(date)}, ${dayMonthFormatter.format(date)}`;
}

/** «завтра, 26 октября, 15:00»; без времени — «завтра, 26 октября»; без срока — «без срока». */
export function formatWhen(event: CalendarEvent): string {
  if (!event.starts_at) return "без срока";
  const offset = dayOffset(event.starts_at);
  const date = new Date(event.starts_at);
  const day =
    offset === 0 || offset === 1
      ? `${formatDayLabel(event.starts_at)}, ${dayMonthFormatter.format(date)}`
      : formatDayLabel(event.starts_at);
  return event.has_time ? `${day}, ${formatTime(event.starts_at)}` : day;
}

/** «25.10.2026» — для плотных таблиц. */
export function formatNumericDate(iso: string): string {
  return numericDateFormatter.format(new Date(iso));
}

/** «вс» */
export function formatShortWeekday(value: string | Date): string {
  return shortWeekdayFormatter.format(typeof value === "string" ? new Date(value) : value);
}

/** «воскресенье» */
export function formatWeekday(value: string | Date): string {
  return weekdayFormatter.format(typeof value === "string" ? new Date(value) : value);
}

/** «25 октября» */
export function formatDayMonth(value: string | Date): string {
  return dayMonthFormatter.format(typeof value === "string" ? new Date(value) : value);
}

/** Минут от «сейчас» демо до начала события; отрицательное — уже началось. */
export function minutesFromNow(iso: string): number {
  return Math.round((Date.parse(iso) - DEMO_NOW.getTime()) / 60_000);
}

/** «через 20 минут», «через 2 часа 50 минут» */
export function formatIn(iso: string): string | null {
  const minutes = minutesFromNow(iso);
  if (minutes <= 0) return null;
  if (minutes < 60)
    return `через ${formatCount(minutes, { one: "минуту", few: "минуты", many: "минут" })}`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  const hoursText = formatCount(hours, { one: "час", few: "часа", many: "часов" });
  return rest === 0
    ? `через ${hoursText}`
    : `через ${hoursText} ${formatCount(rest, { one: "минуту", few: "минуты", many: "минут" })}`;
}

/** Состояние события относительно «сейчас»: прошло, идёт, впереди. */
export function eventTiming(event: CalendarEvent): "done" | "past" | "now" | "next" | "later" {
  if (event.status === "done") return "done";
  if (!event.starts_at) return "later";
  const start = Date.parse(event.starts_at);
  const end = event.ends_at ? Date.parse(event.ends_at) : start;
  const now = DEMO_NOW.getTime();
  if (end < now) return "past";
  if (start <= now) return "now";
  return "later";
}

/** Записи на конкретный день (смещение от сегодня), по времени. */
export function eventsOnDay(events: CalendarEvent[], offset: number): CalendarEvent[] {
  return events
    .filter((event) => event.starts_at !== null && dayOffset(event.starts_at) === offset)
    .sort((a, b) => Date.parse(a.starts_at ?? "") - Date.parse(b.starts_at ?? ""));
}

/** Первое событие сегодня, которое ещё впереди. */
export function nextEvent(events: CalendarEvent[]): CalendarEvent | null {
  const now = DEMO_NOW.getTime();
  return (
    eventsOnDay(events, 0).find(
      (event) => event.status === "open" && Date.parse(event.starts_at ?? "") > now,
    ) ?? null
  );
}

/** Положение «сейчас» внутри дня: индекс первого события после текущего момента. */
export function nowIndex(events: CalendarEvent[]): number {
  const now = DEMO_NOW.getTime();
  const index = events.findIndex((event) => Date.parse(event.starts_at ?? "") > now);
  return index === -1 ? events.length : index;
}

/** Время для подписи: «весь день», если время не указано. */
export function formatEventTime(event: CalendarEvent): string {
  if (!event.starts_at) return "—";
  return event.has_time ? formatTime(event.starts_at) : "весь день";
}

/** «0:07» */
export function formatDuration(seconds: number): string {
  const whole = Math.max(0, Math.floor(seconds));
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, "0")}`;
}
