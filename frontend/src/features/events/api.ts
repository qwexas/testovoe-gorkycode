import { apiClient, unwrap } from "@/lib/api/client";
import type { CalendarEvent, EventStatus } from "@/types/api";

/** Сервер отдаёт не больше 200 записей за запрос. */
const MAX_LIMIT = 200;

export type EventsQuery = {
  /** Полуинтервал [from, to) по `starts_at`. */
  from: Date;
  to: Date;
  status?: EventStatus;
  limit?: number;
};

/** Записи профиля за период, по времени начала. */
export async function fetchEvents(
  query: EventsQuery,
  signal?: AbortSignal,
): Promise<CalendarEvent[]> {
  const { events } = await unwrap(
    apiClient.GET("/api/events", {
      params: {
        query: {
          from: query.from.toISOString(),
          to: query.to.toISOString(),
          status: query.status,
          limit: Math.min(query.limit ?? MAX_LIMIT, MAX_LIMIT),
        },
      },
      signal,
      cache: "no-store",
    }),
  );
  return events;
}
