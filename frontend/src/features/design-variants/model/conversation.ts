/**
 * Мок-«бэкенд» для вариантов: по тексту реплики и ожидаемому уточнению выбирает ответ
 * из mock-data. Нужен только чтобы в демо можно было пройти сценарии руками;
 * настоящий разбор делает LLM на сервере.
 */
import {
  DEMO_NOW_ISO,
  EVENT_MOCKUPS,
  EVENT_TEAM_MEETING,
  INITIAL_FEED,
  assistantMessage,
  baseHistory,
  failureMessage,
  replies,
  userMessage,
} from "./mock-data";
import { eventsOnDay } from "./format";
import type { AssistantReply, CalendarEvent, DemoMessage, DemoPhase, DemoStateId } from "./types";

export type Conversation = {
  messages: DemoMessage[];
  feed: CalendarEvent[];
};

export type Preset = Conversation & {
  phase: DemoPhase;
  /** Окно отмены открыто для последнего ответа. */
  undoOpen: boolean;
};

function normalize(text: string): string {
  return text.toLowerCase().replaceAll("ё", "е").trim();
}

/** Чего ждёт последний ответ ассистента, если пользователь ещё не ответил. */
export function pendingOf(messages: DemoMessage[]): AssistantReply["pending"] {
  const last = messages.at(-1);
  return last?.role === "assistant" ? (last.reply?.pending ?? null) : null;
}

/** «утром» 09:00, «днём» 13:00, «вечером» 19:00, «в 3» → 15:00 (решение Q31). */
function parseTime(text: string): string | null {
  if (text.includes("утр")) return "09:00";
  if (text.includes("днем") || text.includes("обед")) return "13:00";
  if (text.includes("вечер")) return "19:00";
  const match = /(\d{1,2})(?::|\.)?(\d{2})?/.exec(text);
  if (!match) return text.includes("три") ? "15:00" : null;
  let hours = Number(match[1]);
  if (hours >= 1 && hours <= 7) hours += 12;
  if (hours > 23) return null;
  return `${String(hours).padStart(2, "0")}:${match[2] ?? "00"}`;
}

function parseChoice(text: string): number | null {
  if (/перв|^1\b|\b1\b/.test(text)) return 1;
  if (/втор|\b2\b/.test(text) || text.includes("договор")) return 2;
  if (/трет|\b3\b/.test(text) || text.includes("презентац")) return 3;
  if (text.includes("crm")) return 1;
  return null;
}

function withEvent(feed: CalendarEvent[], event: CalendarEvent): CalendarEvent[] {
  return feed.some((item) => item.id === event.id) ? feed : [...feed, event];
}

function withoutEvent(feed: CalendarEvent[], id: number): CalendarEvent[] {
  return feed.filter((item) => item.id !== id);
}

/** Ответ на реплику пользователя и новая лента. */
export function respond(
  rawText: string,
  conversation: Conversation,
): { reply: AssistantReply; feed: CalendarEvent[] } {
  const text = normalize(rawText);
  const { feed } = conversation;
  const pending = pendingOf(conversation.messages);

  if (pending?.expects === "time") {
    const time = parseTime(text);
    if (time) {
      const created = replies.meetingWithIvanCreated(time);
      const event = created.events[0];
      return { reply: created, feed: event ? withEvent(feed, event) : feed };
    }
    return { reply: replies.askTime(), feed };
  }

  if (pending?.expects === "choice") {
    const index = parseChoice(text);
    if (index) return { reply: replies.movedIvanMeeting(index), feed };
    return { reply: replies.chooseIvanMeeting(), feed };
  }

  if (pending?.expects === "confirm") {
    if (/^(да|удали|удалить)/.test(text)) {
      return { reply: replies.deleted(), feed: withoutEvent(feed, EVENT_MOCKUPS.id) };
    }
    return { reply: replies.kept(), feed };
  }

  if (/сегодня|планы|что у меня/.test(text)) {
    return { reply: replies.todayList(eventsOnDay(feed, 0)), feed };
  }
  if (/найди|найти|поиск|когда у меня был|ставил/.test(text)) {
    return { reply: replies.searchPresentation(), feed };
  }
  if (/удали/.test(text)) return { reply: replies.askDelete(), feed };
  if (/перенеси|перенести/.test(text)) return { reply: replies.chooseIvanMeeting(), feed };
  if (/встреч/.test(text)) {
    if (!/\d/.test(text)) return { reply: replies.askTime(), feed };
    return { reply: replies.meetingCreated(), feed: withEvent(feed, EVENT_TEAM_MEETING) };
  }
  if (/напомни/.test(text)) return { reply: replies.reminderCreated(), feed };
  return { reply: replies.notUnderstood(), feed };
}

/** Что «распознал» голосовой ввод в демо: ответ на уточнение или новая встреча. */
export function simulatedRecognition(messages: DemoMessage[]): string {
  switch (pendingOf(messages)?.expects) {
    case "time":
      return "В три часа дня";
    case "choice":
      return "Вторую";
    case "confirm":
      return "Да, удали";
    default:
      return "Добавь встречу с командой завтра в 15:00";
  }
}

/** Отмена последнего действия: убрать созданную запись из ленты. */
export function undoLast(conversation: Conversation): Conversation {
  const last = conversation.messages.at(-1);
  const event = last?.reply?.events[0];
  if (!last?.reply?.undo || !event) return conversation;
  return {
    messages: [
      ...conversation.messages,
      assistantMessage(replies.undone(event.title), DEMO_NOW_ISO),
    ],
    feed: withoutEvent(conversation.feed, event.id),
  };
}

function exchange(userText: string, reply: AssistantReply, via: "voice" | "text" = "voice") {
  return [userMessage(userText, DEMO_NOW_ISO, via), assistantMessage(reply, DEMO_NOW_ISO)];
}

/** Готовые состояния для демо-панели и параметра `?state=`. `now` — performance.now(). */
export function buildPreset(id: DemoStateId, now: number): Preset {
  const base = baseHistory();
  const idle = { name: "idle" } as const;
  const common = { feed: INITIAL_FEED, phase: idle as DemoPhase, undoOpen: false };

  switch (id) {
    case "idle":
      return { ...common, messages: base };
    case "recording":
      return {
        ...common,
        messages: base,
        phase: { name: "recording", startedAt: now, auto: false },
      };
    case "processing":
      return {
        ...common,
        messages: [...base, userMessage("Что у меня на этой неделе?", DEMO_NOW_ISO, "voice")],
        phase: { name: "processing", stage: "thinking", via: "voice", auto: false },
      };
    case "confirmation":
      return {
        ...common,
        messages: [
          ...base,
          ...exchange("Добавь встречу с командой завтра в 15:00", replies.meetingCreated()),
        ],
        feed: withEvent(INITIAL_FEED, EVENT_TEAM_MEETING),
        undoOpen: true,
      };
    case "list":
      return {
        ...common,
        messages: [
          ...base,
          ...exchange("Что у меня сегодня?", replies.todayList(eventsOnDay(INITIAL_FEED, 0))),
        ],
      };
    case "clarification":
      return {
        ...common,
        messages: [...base, ...exchange("Поставь встречу с Иваном завтра", replies.askTime())],
      };
    case "choice":
      return {
        ...common,
        messages: [
          ...base,
          ...exchange("Перенеси встречу с Иваном на четверг", replies.chooseIvanMeeting()),
        ],
      };
    case "search":
      return {
        ...common,
        messages: [
          ...base,
          ...exchange("Найди задачу про презентацию", replies.searchPresentation(), "text"),
        ],
      };
    case "confirm-delete":
      return {
        ...common,
        messages: [...base, ...exchange("Удали встречу с Ольгой", replies.askDelete())],
      };
    case "error":
      return {
        ...common,
        messages: [...base, failureMessage(DEMO_NOW_ISO)],
        phase: { name: "error" },
      };
  }
}

export { failureMessage, userMessage, assistantMessage };
