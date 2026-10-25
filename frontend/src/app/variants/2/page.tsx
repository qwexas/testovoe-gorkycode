import type { Metadata } from "next";
import { Suspense } from "react";

import { type SearchParams, readDemoParams } from "@/features/design-variants/model/search-params";
import { ManuscriptScreen } from "@/features/design-variants/v2/manuscript-screen";

export const metadata: Metadata = { title: "Вариант 2 «Рукопись» — Горький" };

async function Screen({ searchParams }: { searchParams: Promise<SearchParams> }) {
  const { state, showBar } = readDemoParams(await searchParams);
  return <ManuscriptScreen initialState={state} showBar={showBar} />;
}

/** Состояние демо приходит из `?state=` — читаем его внутри Suspense (cacheComponents). */
export default function ManuscriptVariantPage({
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
