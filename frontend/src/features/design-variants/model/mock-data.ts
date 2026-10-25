/**
 * Мок-данные для вариантов дизайна. Формы — ровно как в контракте API
 * (Event, AssistantReply, ChatMessage), чтобы варианты потом подключались к /api без
 * переделки отображения. «Сейчас» зафиксировано: воскресенье, 25 октября 2026, 16:40 МСК.
 */
import type { AssistantReply, CalendarEvent, DemoMessage } from "./types";

export const DEMO_NOW_ISO = "2026-10-25T16:40:00+03:00";
export const DEMO_NOW = new Date(DEMO_NOW_ISO);

const CREATED_AT = "2026-10-20T10:00:00+03:00";

type EventInput = Pick<CalendarEvent, "id" | "type" | "title" | "starts_at"> &
  Partial<Pick<CalendarEvent, "ends_at" | "status" | "source" | "has_time">>;

function makeEvent({
  id,
  type,
  title,
  starts_at,
  ends_at = null,
  status = "open",
  source = "user",
  has_time = true,
}: EventInput): CalendarEvent {
  return {
    id,
    type,
    title,
    starts_at,
    ends_at,
    has_time,
    status,
    source,
    created_at: CREATED_AT,
    updated_at: CREATED_AT,
  };
}

/* ── Лента: сегодня и завтра ─────────────────────────────────────────────── */

export const EVENT_REPORT = makeEvent({
  id: 101,
  type: "task",
  title: "Отправить отчёт Алексею",
  starts_at: "2026-10-25T09:30:00+03:00",
  status: "done",
});

export const EVENT_DESIGNER_CALL = makeEvent({
  id: 102,
  type: "meeting",
  title: "Созвон с дизайнером",
  starts_at: "2026-10-25T12:00:00+03:00",
  ends_at: "2026-10-25T13:00:00+03:00",
});

export const EVENT_MOCKUPS = makeEvent({
  id: 103,
  type: "meeting",
  title: "Разбор макетов с Ольгой",
  starts_at: "2026-10-25T17:00:00+03:00",
  ends_at: "2026-10-25T18:00:00+03:00",
});

export const EVENT_PICKUP = makeEvent({
  id: 104,
  type: "reminder",
  title: "Забрать заказ из пункта выдачи",
  starts_at: "2026-10-25T19:30:00+03:00",
});

/** «Поставь задачу купить билеты до конца недели» → срок вс 23:59 (решение Q31). */
export const EVENT_TICKETS = makeEvent({
  id: 105,
  type: "task",
  title: "Купить билеты на хакатон",
  starts_at: "2026-10-25T23:59:00+03:00",
});

export const EVENT_CALL_IVAN = makeEvent({
  id: 106,
  type: "reminder",
  title: "Позвонить Ивану",
  starts_at: "2026-10-26T10:00:00+03:00",
});

/** Создаётся в сценарии «Подтверждение»: «Добавь встречу с командой завтра в 15:00». */
export const EVENT_TEAM_MEETING = makeEvent({
  id: 107,
  type: "meeting",
  title: "Встреча с командой",
  starts_at: "2026-10-26T15:00:00+03:00",
  ends_at: "2026-10-26T16:00:00+03:00",
});

export const INITIAL_FEED: CalendarEvent[] = [
  EVENT_REPORT,
  EVENT_DESIGNER_CALL,
  EVENT_MOCKUPS,
  EVENT_PICKUP,
  EVENT_TICKETS,
  EVENT_CALL_IVAN,
];

/* ── Совпадения для выбора и история для поиска ──────────────────────────── */

const IVAN_MEETINGS = [
  makeEvent({
    id: 201,
    type: "meeting",
    title: "Созвон с Иваном по CRM",
    starts_at: "2026-10-27T11:00:00+03:00",
    ends_at: "2026-10-27T12:00:00+03:00",
  }),
  makeEvent({
    id: 202,
    type: "meeting",
    title: "Встреча с Иваном по договору",
    starts_at: "2026-10-28T16:00:00+03:00",
    ends_at: "2026-10-28T17:00:00+03:00",
  }),
  makeEvent({
    id: 203,
    type: "meeting",
    title: "Обсудить презентацию с Иваном",
    starts_at: "2026-10-30T10:00:00+03:00",
    ends_at: "2026-10-30T11:00:00+03:00",
  }),
];

/** Записи из CSV-истории (2024 год), как их вернёт поиск по смыслу. */
const PRESENTATION_HISTORY = [
  makeEvent({
    id: 66,
    type: "task",
    title: "Согласовать презентацию с Иваном",
    starts_at: "2024-04-14T09:45:00+03:00",
    status: "done",
    source: "import",
  }),
  makeEvent({
    id: 52,
    type: "meeting",
    title: "Обсудить презентации с Иваном",
    starts_at: "2024-03-17T19:45:00+03:00",
    ends_at: "2024-03-17T20:45:00+03:00",
    status: "done",
    source: "import",
  }),
  makeEvent({
    id: 82,
    type: "task",
    title: "Передать презентацию на согласование",
    starts_at: "2024-05-08T09:45:00+03:00",
    status: "done",
    source: "import",
  }),
  makeEvent({
    id: 32,
    type: "task",
    title: "Проверить презентацию по интеграции",
    starts_at: "2024-02-16T13:00:00+03:00",
    status: "done",
    source: "import",
  }),
];

/* ── Ответы ассистента ───────────────────────────────────────────────────── */

let messageSeq = 1000;

export function nextMessageId(): number {
  messageSeq += 1;
  return messageSeq;
}

function reply(fields: Partial<AssistantReply> & Pick<AssistantReply, "kind" | "text">) {
  const value: AssistantReply = {
    message_id: nextMessageId(),
    recognized_text: null,
    events: [],
    period: null,
    choices: [],
    conflicts: [],
    pending: null,
    undo: null,
    ...fields,
  };
  return value;
}

export const replies = {
  reminderCreated: () =>
    reply({
      kind: "confirmation",
      text: "Напоминание «Позвонить Ивану» — завтра, 26 октября, 10:00",
      events: [EVENT_CALL_IVAN],
    }),
  meetingCreated: () =>
    reply({
      kind: "confirmation",
      text: "Встреча «Встреча с командой» — завтра, 26 октября, 15:00",
      events: [EVENT_TEAM_MEETING],
      undo: { action_id: "act-team-meeting", expires_at: "2026-10-25T16:41:10+03:00" },
    }),
  todayList: (events: CalendarEvent[]) =>
    reply({
      kind: "list",
      text: "Сегодня пять дел, одно уже сделано. Ближайшее — встреча «Разбор макетов с Ольгой» в 17:00.",
      events,
      period: {
        from: "2026-10-25T00:00:00+03:00",
        to: "2026-10-25T23:59:59+03:00",
        label: "сегодня",
      },
    }),
  askTime: () =>
    reply({
      kind: "clarification",
      text: "На какое время поставить встречу?",
      pending: { expects: "time", question: "На какое время поставить встречу?" },
    }),
  meetingWithIvanCreated: (time: string) => {
    const startsAt = `2026-10-26T${time}:00+03:00`;
    const [hours = "0", minutes = "00"] = time.split(":");
    const end = `2026-10-26T${String(Number(hours) + 1).padStart(2, "0")}:${minutes}:00+03:00`;
    const created = makeEvent({
      id: 108,
      type: "meeting",
      title: "Встреча с Иваном",
      starts_at: startsAt,
      ends_at: end,
    });
    return reply({
      kind: "confirmation",
      text: `Встреча «Встреча с Иваном» — завтра, 26 октября, ${time}`,
      events: [created],
      undo: { action_id: "act-ivan-meeting", expires_at: "2026-10-25T16:41:10+03:00" },
    });
  },
  chooseIvanMeeting: () =>
    reply({
      kind: "choice",
      text: "Нашёл три встречи с Иваном. Какую перенести на четверг?",
      choices: IVAN_MEETINGS.map((event, index) => ({ index: index + 1, event })),
      pending: { expects: "choice", question: "Какую встречу перенести на четверг?" },
    }),
  movedIvanMeeting: (index: number) => {
    const picked = IVAN_MEETINGS[index - 1] ?? IVAN_MEETINGS[1];
    const time = picked?.starts_at?.slice(11, 16) ?? "16:00";
    const moved = picked
      ? { ...picked, starts_at: `2026-10-29T${time}:00+03:00`, ends_at: null }
      : undefined;
    return reply({
      kind: "confirmation",
      text: `Перенёс «${picked?.title ?? "встречу"}» на четверг, 29 октября, ${time}`,
      events: moved ? [moved] : [],
      undo: { action_id: "act-move", expires_at: "2026-10-25T16:41:10+03:00" },
    });
  },
  searchPresentation: () =>
    reply({
      kind: "search_results",
      text: "Нашёл 4 записи про презентацию. Ближе всего — «Согласовать презентацию с Иваном», 14 апреля 2024.",
      events: PRESENTATION_HISTORY,
    }),
  askDelete: () =>
    reply({
      kind: "confirm_request",
      text: "Удалить встречу «Разбор макетов с Ольгой» сегодня в 17:00?",
      events: [EVENT_MOCKUPS],
      pending: { expects: "confirm", question: "Удалить встречу?" },
    }),
  deleted: () =>
    reply({
      kind: "confirmation",
      text: "Удалил встречу «Разбор макетов с Ольгой»",
      events: [EVENT_MOCKUPS],
    }),
  kept: () => reply({ kind: "info", text: "Хорошо, встречу оставил." }),
  undone: (title: string) =>
    reply({ kind: "info", text: `Отменил: «${title}» больше нет в плане.` }),
  notUnderstood: () =>
    reply({
      kind: "info",
      text: "Не понял, что сделать. Скажите, например: «Что у меня завтра?» или «Напомни в 9 утра позвонить маме».",
    }),
};

/** Текст ошибки `speech_not_recognized` — так его покажет и озвучит фронт. */
export const SPEECH_NOT_RECOGNIZED = "Не расслышал, повторите ещё раз — или напишите текстом.";

/** Фразы из ТЗ: по одной на каждое ключевое действие. */
export const EXAMPLE_PHRASES = [
  "Что у меня сегодня?",
  "Добавь встречу с командой завтра в 15:00",
  "Найди задачу про презентацию",
  "Напомни мне завтра в 10 утра позвонить Ивану",
] as const;

/* ── Сборка истории ──────────────────────────────────────────────────────── */

export function userMessage(
  text: string,
  createdAt: string,
  via: "voice" | "text" = "text",
): DemoMessage {
  return { id: nextMessageId(), role: "user", text, created_at: createdAt, reply: null, via };
}

export function assistantMessage(value: AssistantReply, createdAt: string): DemoMessage {
  return {
    id: value.message_id,
    role: "assistant",
    text: value.text,
    created_at: createdAt,
    reply: value,
  };
}

export function failureMessage(createdAt: string): DemoMessage {
  return {
    id: nextMessageId(),
    role: "assistant",
    text: SPEECH_NOT_RECOGNIZED,
    created_at: createdAt,
    reply: null,
    failure: "speech_not_recognized",
  };
}

/** Начало разговора, общее для всех состояний: напоминание, поставленное днём. */
export function baseHistory(): DemoMessage[] {
  return [
    userMessage(
      "Напомни мне завтра в 10 утра позвонить Ивану",
      "2026-10-25T14:02:00+03:00",
      "voice",
    ),
    assistantMessage(replies.reminderCreated(), "2026-10-25T14:02:00+03:00"),
  ];
}
