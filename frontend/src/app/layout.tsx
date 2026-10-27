import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";
import { Martian_Mono } from "next/font/google";

import { Providers } from "@/components/providers";
import { themeInitScript } from "@/lib/theme";

import "./globals.css";

/**
 * «Консоль» (решение Q8): одна моноширинная гарнитура с осью ширины. Широкие
 * начертания — заголовки панелей и статус, узкие — плотные таблицы. Кириллица полная.
 */
const martianMono = Martian_Mono({
  variable: "--font-martian-mono",
  subsets: ["latin", "cyrillic"],
  axes: ["wdth"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "Горький — голосовой ассистент задач и встреч",
  description:
    "Горький ставит задачи, напоминания и встречи голосом или текстом, рассказывает о планах на день и находит прошлые записи.",
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f6f4fa" },
    { media: "(prefers-color-scheme: dark)", color: "#0e0b16" },
  ],
};

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    // suppressHydrationWarning: data-theme и color-scheme ставит инлайн-скрипт до гидрации.
    <html lang="ru" suppressHydrationWarning className={`${martianMono.variable} h-full`}>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeInitScript }} />
      </head>
      <body className="flex min-h-full flex-col">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
