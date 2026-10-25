import type { ReactNode } from "react";

const MARK_SIZE = 6;
const MARK_CORNERS = new Set([
  "0-0",
  `${MARK_SIZE - 1}-0`,
  `0-${MARK_SIZE - 1}`,
  `${MARK_SIZE - 1}-${MARK_SIZE - 1}`,
]);
const MARK_PIXELS = Array.from({ length: MARK_SIZE * MARK_SIZE }, (_, index) => ({
  x: index % MARK_SIZE,
  y: Math.floor(index / MARK_SIZE),
})).filter(({ x, y }) => !MARK_CORNERS.has(`${x}-${y}`));

/** Пиксельная метка «Горького»: круг из квадратов — терминальная деталь (решение Q8). */
function BrandMark() {
  return (
    <svg
      width="18"
      height="18"
      viewBox={`0 0 ${MARK_SIZE} ${MARK_SIZE}`}
      aria-hidden="true"
      shapeRendering="crispEdges"
      className="text-accent"
    >
      {MARK_PIXELS.map(({ x, y }) => (
        <rect key={`${x}-${y}`} x={x} y={y} width="1" height="1" fill="currentColor" />
      ))}
    </svg>
  );
}

/** Шапка: название ассистента слева, служебные действия справа. */
export function AppHeader({ actions }: { actions: ReactNode }) {
  return (
    <header className="border-b border-border">
      <div className="mx-auto flex h-16 max-w-6xl items-center gap-2 px-4 sm:px-6">
        <p
          translate="no"
          className="flex items-center gap-2.5 text-lg font-semibold tracking-tight"
        >
          <BrandMark />
          Горький
        </p>
        <div className="ml-auto flex items-center gap-1 sm:gap-2">{actions}</div>
      </div>
    </header>
  );
}
