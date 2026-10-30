/**
 * как показывать записи (Event из контракта) в «Консоли»: подписи типов, время,
 * положение относительно «сейчас». Чистые функции: «сейчас» передаётся явно.
 */
import {
  dayOffset,
  formatCount,
  formatDayMonth,
  formatNumericDate,
  formatShortDate,
  formatShortWeekday,
  formatTime,
  formatWeekday,
  moscowDateKey,
} from "@/lib/format";
import type { CalendarEvent, EventType } from "@/types/api";

export const TYPE_LABELS: Record<EventType, string> = {
  task: "задача",
  reminder: "напоминание",
  meeting: "встреча",
};

/** метка типа формой, а не только цветом (WCAG 1.4.1). Расшифровка — в легенде плана. */
const TYPE_GLYPHS: Record<EventType, string> = {
  task: "[ ]",
  reminder: " ! ",
  meeting: " ◆ ",
};

export function typeGlyph(event: CalendarEvent): string {
  return event.type === "task" && event.status === "done" ? "[x]" : TYPE_GLYPHS[event.type];
}

export type EventTiming = "done" | "past" | "now" | "later";

/** положение записи относительно «сейчас»: сделано, прошло, идёт, впереди. */
export function eventTiming(event: CalendarEvent, now: Date): EventTiming {
  if (event.status === "done") return "done";
  if (!event.starts_at) return "later";
  const start = Date.parse(event.starts_at);
  // задача со сроком «на день» актуальна до конца этого дня.
  const end = event.ends_at
    ? Date.parse(event.ends_at)
    : event.has_time
      ? start
      : start + 86_400_000 - 1;
  const at = now.getTime();
  if (end < at) return "past";
  if (start <= at && event.ends_at) return "now";
  if (start <= at) return event.has_time ? "past" : "later";
  return "later";
}

const MINUTE_FORMS = { one: "минуту", few: "минуты", many: "минут" };
const HOUR_FORMS = { one: "час", few: "часа", many: "часов" };
const DAY_FORMS = { one: "день", few: "дня", many: "дней" };

/**
 * сколько осталось: сегодня — «через 20 минут», «через 2 часа 50 минут»; дальше —
 * по дням: «завтра», «через 3 дня». null — уже наступило.
 */
export function formatIn(iso: string, now: Date): string | null {
  const minutes = Math.round((Date.parse(iso) - now.getTime()) / 60_000);
  if (minutes <= 0) return null;
  const days = dayOffset(iso, now);
  if (days === 1) return "завтра";
  if (days > 1) return `через ${formatCount(days, DAY_FORMS)}`;
  if (minutes < 60) return `через ${formatCount(minutes, MINUTE_FORMS)}`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  const hoursText = formatCount(hours, HOUR_FORMS);
  return rest === 0
    ? `через ${hoursText}`
    : `через ${hoursText} ${formatCount(rest, MINUTE_FORMS)}`;
}

/** «17:00»; без времени — «—» (срок на весь день). */
export function formatEventTime(event: CalendarEvent): string {
  if (!event.starts_at || !event.has_time) return "—";
  return formatTime(event.starts_at);
}

/** «17:00–18:00» для встречи, иначе просто время. */
export function formatTimeRange(event: CalendarEvent): string {
  if (!event.starts_at || !event.has_time) return "—";
  const start = formatTime(event.starts_at);
  return event.ends_at ? `${start}–${formatTime(event.ends_at)}` : start;
}

/** «сегодня», «завтра», «вчера», «вторник, 3 ноября», «14 апреля 2024» */
export function formatDayLabel(iso: string, now: Date): string {
  const offset = dayOffset(iso, now);
  if (offset === 0) return "сегодня";
  if (offset === 1) return "завтра";
  if (offset === -1) return "вчера";
  const date = new Date(iso);
  if (moscowDateKey(date).slice(0, 4) !== moscowDateKey(now).slice(0, 4)) {
    return formatNumericDate(date);
  }
  if (Math.abs(offset) < 7) return `${formatWeekday(date)}, ${formatDayMonth(date)}`;
  return formatDayMonth(date);
}

/** «завтра, 26 октября, 15:00»; без времени — «завтра, 26 октября»; без даты — «без срока». */
export function formatWhen(event: CalendarEvent, now: Date): string {
  if (!event.starts_at) return "без срока";
  const offset = dayOffset(event.starts_at, now);
  const label = formatDayLabel(event.starts_at, now);
  const day = Math.abs(offset) <= 1 ? `${label}, ${formatDayMonth(event.starts_at)}` : label;
  return event.has_time ? `${day}, ${formatTimeRange(event)}` : day;
}

/** «пн 26.10 10:00» — для таблиц за несколько дней. */
export function formatCompactWhen(event: CalendarEvent): string {
  if (!event.starts_at) return "без срока";
  const day = `${formatShortWeekday(event.starts_at)} ${formatShortDate(event.starts_at)}`;
  return event.has_time ? `${day} ${formatTime(event.starts_at)}` : day;
}

/** «25.10.2026 16:30» — для результатов поиска, где важен год. */
export function formatFullWhen(event: CalendarEvent): string {
  if (!event.starts_at) return "без срока";
  const day = formatNumericDate(event.starts_at);
  return event.has_time ? `${day} ${formatTime(event.starts_at)}` : day;
}

function byStart(a: CalendarEvent, b: CalendarEvent): number {
  return Date.parse(a.starts_at ?? "") - Date.parse(b.starts_at ?? "") || a.id - b.id;
}

/** записи на день со смещением от сегодня (0 — сегодня, 1 — завтра), по времени. */
export function eventsOnDay(events: CalendarEvent[], offset: number, now: Date): CalendarEvent[] {
  return events
    .filter((event) => event.starts_at !== null && dayOffset(event.starts_at, now) === offset)
    .sort(byStart);
}

/** ближайшая открытая запись со временем, которая ещё не началась. */
export function nextEvent(events: CalendarEvent[], now: Date): CalendarEvent | null {
  const at = now.getTime();
  return (
    events
      .filter(
        (event) =>
          event.status === "open" &&
          event.has_time &&
          event.starts_at !== null &&
          Date.parse(event.starts_at) > at,
      )
      .sort(byStart)[0] ?? null
  );
}

/** где в списке дня провести линию «сейчас»: индекс первой записи после текущего момента. */
export function nowIndex(events: CalendarEvent[], now: Date): number {
  const at = now.getTime();
  const index = events.findIndex(
    (event) => event.has_time && Date.parse(event.starts_at ?? "") > at,
  );
  return index === -1 ? events.length : index;
}
