"use client";

import type { RefObject } from "react";

import { tty } from "@/components/ui/tty";
import { cn } from "@/lib/cn";
import { formatDuration } from "@/lib/format";

import { useLevelMeter } from "../hooks/use-level-meter";

const METER_CELLS = 12;
/** Восемь ступеней, как у блочных символов ▁▂▃▄▅▆▇█. */
const STEPS = 8;

/**
 * Уровень голоса столбиками, свежие значения справа. Столбики — элементы с высотой
 * в восьмых долях, а не символы ▁…█: у моноширинных шрифтов эти глифы выше строки
 * и наезжают на соседний текст.
 */
function applyMeter(element: HTMLElement, level: number) {
  const bars = Array.from(element.children) as HTMLElement[];
  // Корень растягивает тихие уровни: речь в комнате редко доходит до максимума.
  const step = Math.min(STEPS, Math.round(Math.sqrt(level) * STEPS));
  const history = (element.dataset.history ?? "").split(",").filter(Boolean).map(Number);
  history.push(step);
  const recent = history.slice(-METER_CELLS);
  element.dataset.history = recent.join(",");
  const padded = Array.from({ length: METER_CELLS - recent.length }, () => 0).concat(recent);
  bars.forEach((bar, index) => {
    const value = padded[index] ?? 0;
    bar.style.height = `${Math.max(1, value) * (100 / STEPS)}%`;
    bar.style.opacity = value === 0 ? "0.35" : "1";
  });
}

/**
 * Индикатор записи для панели сферы: уровень с микрофона и длительность. Это обратная
 * связь «микрофон слышит», поэтому работает и при reduced motion (реже).
 */
export function LevelMeter({
  levelRef,
  recording,
  seconds,
}: {
  levelRef: RefObject<number>;
  recording: boolean;
  seconds: number;
}) {
  const meterRef = useLevelMeter<HTMLSpanElement>(levelRef, recording, applyMeter);
  return (
    <p className={cn("flex items-end gap-3", !recording && "hidden")}>
      <span ref={meterRef} className="flex h-6 items-end gap-[3px] sm:h-7" aria-hidden="true">
        {Array.from({ length: METER_CELLS }, (_, index) => (
          <span key={index} className="block h-[12.5%] w-[0.6ch] bg-accent" />
        ))}
      </span>
      <span className={cn(tty.danger, tty.strong, "leading-none")}>
        <span className="sr-only">Идёт запись, </span>
        {formatDuration(seconds)}
      </span>
    </p>
  );
}
