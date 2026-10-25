"use client";

import { useToday } from "../hooks/use-today";

/** «Лента дня»: события на сегодня. На КТ1 — заглушка, GET /api/events ещё отвечает 501. */
export function DayFeed() {
  const today = useToday();

  return (
    <aside
      aria-labelledby="day-feed-title"
      className="rounded-3xl border border-border bg-surface p-5 lg:self-start"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <h2 id="day-feed-title" className="text-base font-semibold">
          Лента дня
        </h2>
        {today ? (
          <time dateTime={today.iso} className="font-mono text-xs text-fg-muted">
            {today.label}
          </time>
        ) : null}
      </div>

      <div className="mt-5 rounded-2xl border border-dashed border-border-strong px-4 py-8 text-center">
        <p className="font-medium">Скоро здесь будет план на день</p>
        <p className="mx-auto mt-1 max-w-[30ch] text-sm text-pretty text-fg-muted">
          Задачи, встречи и напоминания на сегодня — по времени, с отметкой о выполнении.
        </p>
      </div>
    </aside>
  );
}
