import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";
import { JetBrains_Mono, Onest } from "next/font/google";

import { Providers } from "@/components/providers";
import { themeInitScript } from "@/lib/theme";

import "./globals.css";

// Шрифты-кандидаты с кириллицей; финальная пара выбирается на КТ2 вместе с дизайном.
const onest = Onest({
  variable: "--font-onest",
  subsets: ["latin", "cyrillic"],
  display: "swap",
});

const jetbrainsMono = JetBrains_Mono({
  variable: "--font-jetbrains-mono",
  subsets: ["latin", "cyrillic"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "Горький — голосовой ассистент задач и встреч",
  description:
    "Горький ставит задачи, напоминания и встречи голосом или текстом, рассказывает о планах на день и находит прошлые записи.",
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f5f3fa" },
    { media: "(prefers-color-scheme: dark)", color: "#110d19" },
  ],
};

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    // suppressHydrationWarning: data-theme и color-scheme ставит инлайн-скрипт до гидрации.
    <html
      lang="ru"
      suppressHydrationWarning
      className={`${onest.variable} ${jetbrainsMono.variable} h-full`}
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeInitScript }} />
      </head>
      <body className="flex min-h-full flex-col">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
