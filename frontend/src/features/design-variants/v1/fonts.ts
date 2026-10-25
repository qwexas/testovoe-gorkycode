import { Martian_Mono } from "next/font/google";

/**
 * Вариант 1 «Консоль»: одна моноширинная гарнитура с осью ширины. Широкие начертания —
 * заголовки панелей и статус, узкие — плотные таблицы. Кириллица полная.
 */
export const consoleMono = Martian_Mono({
  variable: "--font-v1-mono",
  subsets: ["latin", "cyrillic"],
  axes: ["wdth"],
  display: "swap",
});
