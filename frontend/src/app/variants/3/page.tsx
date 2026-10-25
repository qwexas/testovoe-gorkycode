import type { Metadata } from "next";
import { Suspense } from "react";

import { type SearchParams, readDemoParams } from "@/features/design-variants/model/search-params";
import { BalloonScreen } from "@/features/design-variants/v3/balloon-screen";

export const metadata: Metadata = { title: "Вариант 3 «Шар» — Горький" };

async function Screen({ searchParams }: { searchParams: Promise<SearchParams> }) {
  const { state, showBar } = readDemoParams(await searchParams);
  return <BalloonScreen initialState={state} showBar={showBar} />;
}

/** Состояние демо приходит из `?state=` — читаем его внутри Suspense (cacheComponents). */
export default function BalloonVariantPage({
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
