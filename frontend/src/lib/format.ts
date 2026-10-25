/** Форматирование для интерфейса. Язык и часовой пояс фиксированы (решение Q9). */

export const LOCALE = "ru-RU";
export const TIME_ZONE = "Europe/Moscow";

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

const numberFormatter = new Intl.NumberFormat(LOCALE);
const pluralRules = new Intl.PluralRules(LOCALE);

/** «суббота, 26 октября» */
export function formatDay(date: Date): string {
  return dayFormatter.format(date);
}

/** «25 октября 2026 г.» */
export function formatDate(value: string | Date): string {
  return dateFormatter.format(typeof value === "string" ? new Date(value) : value);
}

export type PluralForms = { one: string; few: string; many: string };

/** «1 000 записей», «21 запись», «3 записи» */
export function formatCount(count: number, forms: PluralForms): string {
  const category = pluralRules.select(count);
  const word = category === "one" ? forms.one : category === "few" ? forms.few : forms.many;
  return `${numberFormatter.format(count)} ${word}`;
}
