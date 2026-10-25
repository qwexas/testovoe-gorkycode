import { Geologica, Tiny5 } from "next/font/google";

/**
 * Вариант 3 «Шар». Tiny5 — пиксельный шрифт с чёткой кириллицей (у Pixelify Sans «ь» и «в»
 * читаются как «b» и «e», у DotGothic16 кириллица моноширинная и разрежённая). Кегли —
 * кратные 10 px, чтобы пиксели не мылились. Geologica — гротеск для списков и полей.
 */
export const balloonPixel = Tiny5({
  variable: "--font-v3-pixel",
  weight: "400",
  subsets: ["latin", "cyrillic"],
  display: "swap",
});

export const balloonSans = Geologica({
  variable: "--font-v3-sans",
  subsets: ["latin", "cyrillic"],
  display: "swap",
});
