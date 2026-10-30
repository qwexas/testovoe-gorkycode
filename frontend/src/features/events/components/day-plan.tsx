"use client";

import { Fragment, type ReactNode } from "react";

import { tty } from "@/components/ui/tty";
import { cn } from "@/lib/cn";
import {
  dayOffset,
  formatDayMonth,
  formatShortWeekday,
  formatTime,
  moscowDateKey,
  moscowMidnight,
} from "@/lib/format";
import type { CalendarEvent } from "@/types/api";

import type { DayPlan } from "../hooks/use-day-plan";
import {
  TYPE_LABELS,
  eventTiming,
  eventsOnDay,
  formatEventTime,
  formatIn,
  nowIndex,
  typeGlyph,
} from "../model/event-format";

function Row({ event, now, fresh }: { event: CalendarEvent; now: Date; fresh: boolean }) {
  const timing = eventTiming(event, now);
  const muted = timing === "done" || timing === "past";
  // только для сегодняшних: у завтрашних день и так в заголовке.
  const soon =
    timing === "later" && event.starts_at && event.has_time && dayOffset(event.starts_at, now) === 0
      ? formatIn(event.starts_at, now)
      : null;
  let note: string | null = null;
  if (event.ends_at && !muted) note = `до ${formatTime(event.ends_at)}${soon ? `, ${soon}` : ""}`;
  else if (timing === "now") note = "идёт сейчас";
  else if (soon) note = soon;
  else if (event.type === "task" && !event.has_time && timing === "later")
    note = "срок до конца дня";

  return (
    <li
      className={cn(
        "grid grid-cols-[5ch_3ch_minmax(0,1fr)] gap-x-[1ch] px-3 py-1",
        fresh && tty.fresh,
      )}
    >
      <span className={cn(muted && tty.muted)}>{formatEventTime(event)}</span>
      <span
        className={cn(event.type === "meeting" ? tty.accent : tty.wait, "whitespace-pre")}
        aria-hidden="true"
      >
        {typeGlyph(event)}
      </span>
      <span className="min-w-0 break-words">
        <span className={cn(muted && tty.muted, timing === "done" && tty.struck)}>
          {event.title}
        </span>
        <span className="sr-only">, {TYPE_LABELS[event.type]}</span>
        {timing === "done" ? <span className="sr-only">, выполнено</span> : null}
        {note ? <span className={cn(tty.muted, "block text-xs")}>{note}</span> : null}
      </span>
    </li>
  );
}

function NowLine({ now }: { now: Date }) {
  return (
    <li className={cn(tty.nowLine, "px-3 py-1")}>
      <span>
        {formatTime(now)} <span className="sr-only">—</span>сейчас
      </span>
    </li>
  );
}

function DayList({
  events,
  now,
  withNow,
  freshIds,
}: {
  events: CalendarEvent[];
  now: Date;
  withNow: boolean;
  freshIds: ReadonlySet<number>;
}) {
  const nowAt = withNow ? nowIndex(events, now) : -1;
  return (
    <ul className="grid">
      {events.map((event, index) => (
        <Fragment key={event.id}>
          {index === nowAt ? <NowLine now={now} /> : null}
          <Row event={event} now={now} fresh={freshIds.has(event.id)} />
        </Fragment>
      ))}
      {withNow && nowAt === events.length ? <NowLine now={now} /> : null}
    </ul>
  );
}

function Message({ children, tone }: { children: ReactNode; tone?: "danger" }) {
  return (
    <p className={cn("px-3 text-pretty", tone === "danger" ? tty.danger : tty.muted)}>{children}</p>
  );
}

/**
 * план дня: сегодня по времени с линией «сейчас», ниже — завтра.
 * `footer` — место для настроек напоминаний (их ведёт другая фича).
 */
export function DayPlanView({
  plan,
  now,
  freshIds,
  onRetry,
  footer,
}: {
  plan: DayPlan;
  now: Date | null;
  freshIds: ReadonlySet<number>;
  onRetry: () => void;
  footer?: ReactNode;
}) {
  if (plan.status === "idle" || plan.status === "loading" || !now) {
    return (
      <div className="py-4" aria-busy="true">
        <Message>загружаю план…</Message>
      </div>
    );
  }
  if (plan.status === "failed") {
    return (
      <div className="grid justify-items-start gap-1 py-4">
        <Message tone="danger">
          <span aria-hidden="true">✗ </span>
          План не загрузился. {plan.error.message}
        </Message>
        <div className="px-2">
          <button type="button" onClick={onRetry} className={tty.btn}>
            загрузить снова
          </button>
        </div>
      </div>
    );
  }

  const today = eventsOnDay(plan.events, 0, now);
  const tomorrow = eventsOnDay(plan.events, 1, now);
  const tomorrowDate = moscowMidnight(moscowDateKey(now), 1);

  return (
    <div className="grid content-start gap-5 py-4">
      <section aria-labelledby="plan-today">
        <h3 id="plan-today" className={cn(tty.strong, tty.wide, "px-3 pb-1")}>
          сегодня, {formatShortWeekday(now)} {formatDayMonth(now)}
        </h3>
        {today.length > 0 ? (
          <DayList events={today} now={now} withNow freshIds={freshIds} />
        ) : (
          <Message>на сегодня ничего нет</Message>
        )}
      </section>
      <section aria-labelledby="plan-tomorrow">
        <h3 id="plan-tomorrow" className={cn(tty.strong, tty.wide, "px-3 pb-1")}>
          завтра, {formatShortWeekday(tomorrowDate)} {formatDayMonth(tomorrowDate)}
        </h3>
        {tomorrow.length > 0 ? (
          <DayList events={tomorrow} now={now} withNow={false} freshIds={freshIds} />
        ) : (
          <Message>пока пусто</Message>
        )}
      </section>
      {plan.error ? (
        <Message tone="danger">
          <span aria-hidden="true">✗ </span>
          Не обновился: {plan.error.message}
        </Message>
      ) : null}
      <p className={cn(tty.muted, "px-3 text-xs whitespace-pre-wrap")} aria-hidden="true">
        {"[ ] задача   ◆ встреча   ! напоминание"}
      </p>
      {footer}
    </div>
  );
}
