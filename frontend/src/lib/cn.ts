/** Склеивает классы, отбрасывая пустые значения. Конфликты классов не разрешает. */
export function cn(...classes: Array<string | false | null | undefined>): string {
  return classes.filter(Boolean).join(" ");
}
