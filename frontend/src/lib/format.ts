/** Форматирование для интерфейса. Язык и часовой пояс фиксированы (решение Q9). */

export const LOCALE = "ru-RU";
export const TIME_ZONE = "Europe/Moscow";
/** Москва живёт без перехода на летнее время: смещение всегда +03:00. */
const MOSCOW_OFFSET = "+03:00";
const DAY_MS = 86_400_000;

function toDate(value: string | Date): Date {
  return typeof value === "string" ? new Date(value) : value;
}

const dayFormatter = new Intl.DateTimeFormat(LOCALE, {
  timeZone: TIME_ZONE,
  weekday: "long",
  day: "numeric",
  month: "long",
});

const dateFormatter = new Intl.DateTimeFormat(LOCALE, {
  timeZone: TIME_ZONE,
  day: "numeric",
  month: "long",
  year: "numeric",
});

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

const weekdayFormatter = new Intl.DateTimeFormat(LOCALE, { timeZone: TIME_ZONE, weekday: "long" });

const shortWeekdayFormatter = new Intl.DateTimeFormat(LOCALE, {
  timeZone: TIME_ZONE,
  weekday: "short",
});

const numericDateFormatter = new Intl.DateTimeFormat(LOCALE, {
  timeZone: TIME_ZONE,
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
});

const shortNumericDateFormatter = new Intl.DateTimeFormat(LOCALE, {
  timeZone: TIME_ZONE,
  day: "2-digit",
  month: "2-digit",
});

const dateKeyFormatter = new Intl.DateTimeFormat("en-CA", {
  timeZone: TIME_ZONE,
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
});

const numberFormatter = new Intl.NumberFormat(LOCALE);
const pluralRules = new Intl.PluralRules(LOCALE);

/** «суббота, 26 октября» */
export function formatDay(date: Date): string {
  return dayFormatter.format(date);
}

/** «25 октября 2026 г.» */
export function formatDate(value: string | Date): string {
  return dateFormatter.format(toDate(value));
}

/** «17:00» по Москве */
export function formatTime(value: string | Date): string {
  return timeFormatter.format(toDate(value));
}

/** «25 октября» */
export function formatDayMonth(value: string | Date): string {
  return dayMonthFormatter.format(toDate(value));
}

/** «воскресенье» */
export function formatWeekday(value: string | Date): string {
  return weekdayFormatter.format(toDate(value));
}

/** «вс» */
export function formatShortWeekday(value: string | Date): string {
  return shortWeekdayFormatter.format(toDate(value));
}

/** «25.10.2026» — для плотных таблиц. */
export function formatNumericDate(value: string | Date): string {
  return numericDateFormatter.format(toDate(value));
}

/** «25.10» */
export function formatShortDate(value: string | Date): string {
  return shortNumericDateFormatter.format(toDate(value));
}

/** Календарный день по Москве: «2026-10-25». */
export function moscowDateKey(value: string | Date): string {
  return dateKeyFormatter.format(toDate(value));
}

/** Полночь по Москве для календарного дня «2026-10-25», со сдвигом на `days` дней. */
export function moscowMidnight(dateKey: string, days = 0): Date {
  return new Date(Date.parse(`${dateKey}T00:00:00${MOSCOW_OFFSET}`) + days * DAY_MS);
}

/** Сдвиг в календарных днях по Москве: 0 — тот же день, 1 — следующий. */
export function dayOffset(value: string | Date, now: Date): number {
  const target = Date.parse(`${moscowDateKey(value)}T12:00:00${MOSCOW_OFFSET}`);
  const today = Date.parse(`${moscowDateKey(now)}T12:00:00${MOSCOW_OFFSET}`);
  return Math.round((target - today) / DAY_MS);
}

export type PluralForms = { one: string; few: string; many: string };

/** Нужная форма слова после числа: 1 запись, 3 записи, 5 записей. */
export function pluralWord(count: number, forms: PluralForms): string {
  const category = pluralRules.select(count);
  return category === "one" ? forms.one : category === "few" ? forms.few : forms.many;
}

/** «1 000 записей», «21 запись», «3 записи» */
export function formatCount(count: number, forms: PluralForms): string {
  return `${numberFormatter.format(count)} ${pluralWord(count, forms)}`;
}

/** «0:07» */
export function formatDuration(seconds: number): string {
  const whole = Math.max(0, Math.floor(seconds));
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, "0")}`;
}
