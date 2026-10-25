import { Literata, Ysabeau_Office } from "next/font/google";

/**
 * Вариант 2 «Рукопись». Literata — книжная антиква с оптическими размерами: ей говорит
 * Горький. Ysabeau Office — гуманистический гротеск для интерфейса и реплик человека.
 */
export const manuscriptSerif = Literata({
  variable: "--font-v2-serif",
  subsets: ["latin", "cyrillic"],
  style: ["normal", "italic"],
  axes: ["opsz"],
  display: "swap",
});

export const manuscriptSans = Ysabeau_Office({
  variable: "--font-v2-sans",
  subsets: ["latin", "cyrillic"],
  display: "swap",
});
