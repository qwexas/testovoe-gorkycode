import { tty } from "@/components/ui/tty";
import {
  TYPE_LABELS,
  eventTiming,
  formatCompactWhen,
  formatEventTime,
  formatFullWhen,
  formatIn,
} from "@/features/events/model/event-format";
import { cn } from "@/lib/cn";
import type { CalendarEvent } from "@/types/api";

/**
 * Как подписывать время: `time` — список за один день (только часы), `day` — за несколько
 * дней («пн 26.10 10:00»), `date` — поиск по всей истории (с годом и статусом).
 */
export type TableScale = "time" | "day" | "date";

type Cell = { text: string; className?: string };

function statusCell(event: CalendarEvent, now: Date | null): Cell {
  if (!now) return { text: "" };
  const timing = eventTiming(event, now);
  if (timing === "done") return { text: "сделано", className: tty.ok };
  if (timing === "past") return { text: "прошло", className: tty.muted };
  if (timing === "now") return { text: "идёт", className: tty.accent };
  if (!event.starts_at) return { text: "без срока" };
  return {
    text: event.has_time ? (formatIn(event.starts_at, now) ?? "") : "до конца дня",
    className: tty.muted,
  };
}

function searchStatusCell(event: CalendarEvent): Cell {
  return event.status === "done"
    ? { text: "выполнено", className: tty.ok }
    : { text: "открыто", className: tty.accent };
}

function whenText(event: CalendarEvent, scale: TableScale): string {
  if (scale === "date") return formatFullWhen(event);
  if (scale === "day") return formatCompactWhen(event);
  return formatEventTime(event);
}

const WHEN_HEADERS: Record<TableScale, string> = { time: "время", day: "когда", date: "дата" };

/** Вывод «команды» — таблица записей: время, тип, что и статус. */
export function EventsTable({
  events,
  scale,
  now,
  caption,
  highlightNext = false,
}: {
  events: CalendarEvent[];
  scale: TableScale;
  now: Date | null;
  caption: string;
  /** Подсветить ближайшую предстоящую запись (для списка «что у меня…»). */
  highlightNext?: boolean;
}) {
  if (events.length === 0) return null;
  const isSearch = scale === "date";
  const nextId =
    highlightNext && now
      ? events.find((event) => eventTiming(event, now) === "later")?.id
      : undefined;

  return (
    <div className="mt-2 overflow-x-auto">
      <table className={cn(tty.table, "w-full max-w-[46rem]")}>
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr>
            <th scope="col">{WHEN_HEADERS[scale]}</th>
            <th scope="col" className="max-sm:hidden">
              тип
            </th>
            <th scope="col">что</th>
            <th scope="col" className="max-sm:hidden">
              статус
            </th>
          </tr>
        </thead>
        <tbody>
          {events.map((event) => {
            const status = isSearch ? searchStatusCell(event) : statusCell(event, now);
            const done = event.status === "done" && !isSearch;
            return (
              <tr
                key={event.id}
                className={cn(done && tty.rowDone, event.id === nextId && tty.rowNext)}
              >
                <td className="whitespace-nowrap">{whenText(event, scale)}</td>
                <td className="whitespace-nowrap max-sm:hidden">{TYPE_LABELS[event.type]}</td>
                <td className="break-words sm:min-w-[22ch]">
                  <span className={cn(done && tty.struck)}>{event.title}</span>
                  <span className="block text-xs sm:hidden">
                    {TYPE_LABELS[event.type]}
                    {status.text ? `, ${status.text}` : ""}
                  </span>
                </td>
                <td className={cn("whitespace-nowrap max-sm:hidden", status.className)}>
                  {status.text}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
