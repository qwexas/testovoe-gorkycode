"use client";

import { useEffect, useRef } from "react";

import { formatTime } from "@/lib/format";
import type { CalendarEvent } from "@/types/api";

import { playChime } from "../lib/chime";
import { showNotification } from "../lib/notifications";

/** Пропущенное дольше этого (компьютер спал) уже не звеним — оно видно в плане дня. */
const STALE_MS = 10 * 60_000;

export type Alarm = { key: string; event: CalendarEvent; text: string };

function alarmCopy(event: CalendarEvent): { title: string; body: string; text: string } {
  const time = event.starts_at ? formatTime(event.starts_at) : "";
  switch (event.type) {
    case "reminder":
      return {
        title: "Горький: напоминание",
        body: `${event.title}, ${time}`,
        text: `Напоминание: «${event.title}».`,
      };
    case "meeting":
      return {
        title: "Горький: встреча",
        body: `${event.title} — начинается в ${time}`,
        text: `Начинается встреча «${event.title}».`,
      };
    case "task":
      return {
        title: "Горький: срок задачи",
        body: `${event.title}, срок в ${time}`,
        text: `Подошёл срок задачи «${event.title}».`,
      };
  }
}

/**
 * Напоминания, пока вкладка открыта (решение Q32б): раз в минуту смотрит открытые записи
 * со временем и в момент срока показывает уведомление браузера, играет короткий сигнал
 * и пишет строку в лог (`onAlarm`). Срабатывает только то, чей срок наступил после
 * открытия страницы, — старое не звенит при перезагрузке.
 */
export function useReminders({
  events,
  now,
  onAlarm,
}: {
  /** Записи на ближайшие сутки и дальше (план на сегодня и завтра). */
  events: CalendarEvent[] | null;
  /** Часы с точностью до минуты: каждое новое значение — повод проверить. */
  now: Date | null;
  onAlarm: (alarm: Alarm) => void;
}): void {
  const lastCheck = useRef<number | null>(null);
  const fired = useRef(new Set<string>());
  const onAlarmRef = useRef(onAlarm);

  useEffect(() => {
    onAlarmRef.current = onAlarm;
  });

  useEffect(() => {
    if (!events || !now) return;
    const at = Date.now();
    const since = lastCheck.current ?? at;
    lastCheck.current = at;

    for (const event of events) {
      if (event.status !== "open" || !event.has_time || !event.starts_at) continue;
      const startsAt = Date.parse(event.starts_at);
      if (startsAt <= since || startsAt > at || at - startsAt > STALE_MS) continue;
      const key = `${event.id}@${event.starts_at}`;
      if (fired.current.has(key)) continue;
      fired.current.add(key);

      const copy = alarmCopy(event);
      showNotification(copy.title, copy.body, `gorky-${key}`);
      playChime();
      onAlarmRef.current({ key, event, text: copy.text });
    }
  }, [events, now]);
}
