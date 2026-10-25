import { Fragment } from "react";

import { cn } from "@/lib/cn";

import { DEMO_NOW, EVENT_TEAM_MEETING } from "../model/mock-data";
import {
  TYPE_LABELS,
  eventTiming,
  eventsOnDay,
  formatDayMonth,
  formatEventTime,
  formatIn,
  formatShortWeekday,
  formatTime,
  nowIndex,
} from "../model/format";
import type { CalendarEvent } from "../model/types";
import { styles } from "./styles";

/** Метка типа: форма, а не только цвет (WCAG 1.4.1). Расшифровка — в легенде. */
const GLYPHS: Record<CalendarEvent["type"], string> = {
  task: "[ ]",
  reminder: " ! ",
  meeting: " ◆ ",
};

function glyph(event: CalendarEvent): string {
  return event.type === "task" && event.status === "done" ? "[x]" : GLYPHS[event.type];
}

function Row({ event, fresh }: { event: CalendarEvent; fresh: boolean }) {
  const timing = eventTiming(event);
  const muted = timing === "done" || timing === "past";
  const soon = timing === "later" && event.starts_at ? formatIn(event.starts_at) : null;
  return (
    <li
      className={cn(
        "grid grid-cols-[5ch_3ch_minmax(0,1fr)] gap-x-[1ch] px-3 py-1",
        fresh && styles.fresh,
      )}
    >
      <span className={cn(muted && styles.muted)}>{formatEventTime(event)}</span>
      <span
        className={cn(event.type === "meeting" ? styles.accent : styles.wait, "whitespace-pre")}
        aria-hidden="true"
      >
        {glyph(event)}
      </span>
      <span className="min-w-0">
        <span className={cn(muted && styles.muted, timing === "done" && styles.struck)}>
          {event.title}
        </span>
        <span className="sr-only">, {TYPE_LABELS[event.type]}</span>
        {timing === "done" ? <span className="sr-only">, выполнено</span> : null}
        {event.ends_at && !muted ? (
          <span className={cn(styles.muted, "block text-xs")}>
            до {formatTime(event.ends_at)}
            {soon ? `, ${soon}` : ""}
          </span>
        ) : soon && event.type !== "task" ? (
          <span className={cn(styles.muted, "block text-xs")}>{soon}</span>
        ) : null}
        {event.type === "task" && timing === "later" ? (
          <span className={cn(styles.muted, "block text-xs")}>срок до конца дня</span>
        ) : null}
      </span>
    </li>
  );
}

function DayList({ events, withNow }: { events: CalendarEvent[]; withNow: boolean }) {
  const now = withNow ? nowIndex(events) : -1;
  return (
    <ul className="grid">
      {events.map((event, index) => (
        <Fragment key={event.id}>
          {index === now ? (
            <li className={cn(styles.nowLine, "px-3 py-1")}>
              {formatTime(DEMO_NOW.toISOString())} сейчас
            </li>
          ) : null}
          <Row event={event} fresh={event.id === EVENT_TEAM_MEETING.id} />
        </Fragment>
      ))}
      {withNow && now === events.length ? (
        <li className={cn(styles.nowLine, "px-3 py-1")}>
          {formatTime(DEMO_NOW.toISOString())} сейчас
        </li>
      ) : null}
    </ul>
  );
}

/** Лента дня: сегодня по времени с линией «сейчас», ниже — завтра. */
export function ConsoleDay({ feed }: { feed: CalendarEvent[] }) {
  const today = eventsOnDay(feed, 0);
  const tomorrow = eventsOnDay(feed, 1);
  const tomorrowDate = new Date(DEMO_NOW.getTime() + 86_400_000);

  return (
    <div className="grid content-start gap-5 py-4">
      <section aria-labelledby="v1-today">
        <h2 id="v1-today" className={cn(styles.strong, styles.wide, "px-3 pb-1")}>
          сегодня, {formatShortWeekday(DEMO_NOW)} {formatDayMonth(DEMO_NOW)}
        </h2>
        <DayList events={today} withNow />
      </section>
      <section aria-labelledby="v1-tomorrow">
        <h2 id="v1-tomorrow" className={cn(styles.strong, styles.wide, "px-3 pb-1")}>
          завтра, {formatShortWeekday(tomorrowDate)} {formatDayMonth(tomorrowDate)}
        </h2>
        {tomorrow.length > 0 ? (
          <DayList events={tomorrow} withNow={false} />
        ) : (
          <p className={cn(styles.muted, "px-3")}>пока пусто</p>
        )}
      </section>
      <p className={cn(styles.muted, "px-3 text-xs whitespace-pre-wrap")} aria-hidden="true">
        {"[ ] задача   ◆ встреча   ! напоминание"}
      </p>
    </div>
  );
}
