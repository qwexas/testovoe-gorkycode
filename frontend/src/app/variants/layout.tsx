import type { Metadata } from "next";
import type { ReactNode } from "react";

export const metadata: Metadata = {
  title: "Варианты дизайна — Горький",
  description: "Три направления главного экрана голосового ассистента «Горький» для выбора на КТ2.",
  robots: { index: false, follow: false },
};

export default function VariantsLayout({ children }: { children: ReactNode }) {
  return children;
}
