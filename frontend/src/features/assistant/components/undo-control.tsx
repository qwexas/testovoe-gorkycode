import type { MouseEvent } from "react";

import { tty } from "@/components/ui/tty";
import { cn } from "@/lib/cn";

const UNDO_CELLS = 10;

/**
 * «Отменить» с полоской-отсчётом в десять клеток (решение Q33: окно 10 с). Клетки —
 * элементы, а не символы █░: у моноширинных шрифтов блочные глифы рвутся и прыгают.
 */
export function UndoControl({
  seconds,
  onUndo,
}: {
  seconds: number;
  onUndo: (event: MouseEvent<HTMLButtonElement>) => void;
}) {
  const filled = Math.max(0, Math.min(UNDO_CELLS, seconds));
  return (
    <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1">
      <button type="button" onClick={onUndo} className={tty.btn}>
        отменить
      </button>
      <span className="flex items-center gap-[2px]" aria-hidden="true">
        {Array.from({ length: UNDO_CELLS }, (_, index) => (
          <span
            key={index}
            className={cn("block h-[1em] w-[0.6ch]", index < filled ? "bg-accent" : "bg-accent/25")}
          />
        ))}
      </span>
      <span className={cn(tty.muted, "text-xs")}>ещё {seconds} с</span>
    </div>
  );
}
