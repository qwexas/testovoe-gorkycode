import type { Metadata } from "next";
import { Suspense } from "react";

import { type SearchParams, readDemoParams } from "@/features/design-variants/model/search-params";
import { ConsoleScreen } from "@/features/design-variants/v1/console-screen";

export const metadata: Metadata = { title: "Вариант 1 «Консоль» — Горький" };

async function Screen({ searchParams }: { searchParams: Promise<SearchParams> }) {
  const { state, showBar } = readDemoParams(await searchParams);
  return <ConsoleScreen initialState={state} showBar={showBar} />;
}

/** Состояние демо приходит из `?state=` — читаем его внутри Suspense (cacheComponents). */
export default function ConsoleVariantPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  return (
    <Suspense fallback={<div className="h-dvh bg-bg" />}>
      <Screen searchParams={searchParams} />
    </Suspense>
  );
}
