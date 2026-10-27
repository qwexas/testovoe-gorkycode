/**
 * Состояние сессии разговора: лог реплик (с сервера и локальные строки об ошибках и
 * напоминаниях), что происходит прямо сейчас и окна отмены. Чистый редьюсер без React
 * и сети — переходы проверяются без браузера.
 */
import type { AssistantReply, ChatMessage, Pending } from "@/types/api";

export type Via = "voice" | "text";

/** Что можно сделать прямо из строки лога. */
export type NoticeAction =
  | { type: "record" }
  | { type: "type" }
  | { type: "resend"; text: string }
  | { type: "reload-history" };

/** Почему сфера в состоянии ошибки — от этого зависит подпись. */
export type FailureKind = "not-heard" | "microphone" | "offline" | "busy" | "unavailable" | "error";

export type UserEntry = {
  kind: "user";
  key: string;
  text: string;
  createdAt: string;
  /** null — реплика из истории: как её произнесли, сервер не хранит. */
  via: Via | null;
  /** Ответа не было (сеть, 503, 429): строка остаётся в логе, вопрос ассистента — в силе. */
  failed: boolean;
};

export type AssistantEntry = {
  kind: "assistant";
  key: string;
  messageId: number;
  text: string;
  createdAt: string;
  reply: AssistantReply | null;
  /** Пришёл в этой сессии (не из истории): можно подсветить и озвучить. */
  live: boolean;
};

export type NoticeEntry = {
  kind: "notice";
  key: string;
  createdAt: string;
  tone: "error" | "alarm";
  text: string;
  actions: NoticeAction[];
};

export type LogEntry = UserEntry | AssistantEntry | NoticeEntry;

export type Activity = { name: "idle" } | { name: "sending"; via: Via };

export type ConversationState = {
  /** Чья это история: при смене профиля всё начинается заново. */
  profileId: string | null;
  entries: LogEntry[];
  history: "loading" | "ready" | "failed";
  hasOlder: boolean;
  loadingOlder: boolean;
  activity: Activity;
  failure: FailureKind | null;
  /** id реплики ассистента → до какого момента (performance.now()) показывать «Отменить». */
  undoUntil: Record<number, number>;
  /** Записи, которые изменил последний ответ (если он что-то менял): подсветка в плане дня. */
  changedIds: number[];
};

export type ConversationAction =
  | { type: "history_loaded"; profileId: string; messages: ChatMessage[]; hasOlder: boolean }
  | { type: "history_failed"; profileId: string }
  | { type: "older_loading" }
  | { type: "older_loaded"; messages: ChatMessage[]; hasOlder: boolean }
  | { type: "older_failed" }
  | { type: "user_sent"; entry: UserEntry }
  | { type: "voice_sending" }
  | {
      type: "replied";
      reply: AssistantReply;
      at: string;
      /** Для голоса: распознанная реплика пользователя. */
      recognized?: { key: string; text: string };
      undoUntil: number | null;
    }
  | {
      type: "failed";
      notice: NoticeEntry;
      failure: FailureKind;
      /** Реплика, на которую ответа не было. */
      userKey?: string;
    }
  | { type: "notice"; notice: NoticeEntry; failure?: FailureKind }
  | { type: "undo_started"; messageId: number }
  | { type: "undo_expired"; messageId: number }
  | { type: "clear_failure" };

let localCounter = 0;

/** Уникальный ключ для строк, которых нет на сервере (реплика в пути, ошибка, напоминание). */
export function localKey(prefix: string): string {
  localCounter += 1;
  return `${prefix}-${Date.now().toString(36)}-${localCounter}`;
}

/** Строка лога от интерфейса: ошибка с подсказкой или сработавшее напоминание. */
export function createNotice(
  text: string,
  tone: NoticeEntry["tone"] = "error",
  actions: NoticeAction[] = [],
): NoticeEntry {
  return {
    kind: "notice",
    key: localKey("notice"),
    createdAt: new Date().toISOString(),
    tone,
    text,
    actions,
  };
}

export const initialConversation: ConversationState = {
  profileId: null,
  entries: [],
  history: "loading",
  hasOlder: false,
  loadingOlder: false,
  activity: { name: "idle" },
  failure: null,
  undoUntil: {},
  changedIds: [],
};

export function entryFromMessage(message: ChatMessage, answered = true): LogEntry {
  if (message.role === "user") {
    return {
      kind: "user",
      key: `m${message.id}`,
      text: message.text,
      createdAt: message.created_at,
      via: null,
      failed: !answered,
    };
  }
  return {
    kind: "assistant",
    key: `m${message.id}`,
    messageId: message.id,
    text: message.text,
    createdAt: message.created_at,
    reply: message.reply,
    live: false,
  };
}

function assistantEntry(reply: AssistantReply, at: string): AssistantEntry {
  return {
    kind: "assistant",
    key: `m${reply.message_id}`,
    messageId: reply.message_id,
    text: reply.text,
    createdAt: at,
    reply,
    live: true,
  };
}

function entriesFromHistory(messages: ChatMessage[], nextRole?: ChatMessage["role"]): LogEntry[] {
  return messages.map((message, index) =>
    entryFromMessage(message, (messages[index + 1]?.role ?? nextRole) === "assistant"),
  );
}

/** Склеивает реплики без повторов по ключу, сохраняя порядок. */
function merge(first: LogEntry[], second: LogEntry[]): LogEntry[] {
  const seen = new Set<string>();
  return [...first, ...second].filter((entry) => {
    if (seen.has(entry.key)) return false;
    seen.add(entry.key);
    return true;
  });
}

function withoutKey(record: Record<number, number>, key: number): Record<number, number> {
  const next = { ...record };
  delete next[key];
  return next;
}

export function conversationReducer(
  state: ConversationState,
  action: ConversationAction,
): ConversationState {
  switch (action.type) {
    case "history_loaded": {
      const history = entriesFromHistory(action.messages);
      if (state.profileId !== action.profileId) {
        return {
          ...initialConversation,
          profileId: action.profileId,
          entries: history,
          history: "ready",
          hasOlder: action.hasOlder,
        };
      }
      return {
        ...state,
        // Реплики, пришедшие, пока грузилась история, остаются в конце.
        entries: merge(history, state.entries),
        history: "ready",
        hasOlder: action.hasOlder,
      };
    }
    case "history_failed":
      return state.profileId === action.profileId
        ? { ...state, history: "failed" }
        : { ...initialConversation, profileId: action.profileId, history: "failed" };
    case "older_loading":
      return { ...state, loadingOlder: true };
    case "older_loaded": {
      const firstLoaded = state.entries.find((entry) => entry.key.startsWith("m"));
      const nextRole = firstLoaded && (firstLoaded.kind === "assistant" ? "assistant" : "user");
      return {
        ...state,
        entries: merge(entriesFromHistory(action.messages, nextRole), state.entries),
        hasOlder: action.hasOlder,
        loadingOlder: false,
      };
    }
    case "older_failed":
      return { ...state, loadingOlder: false };
    case "user_sent":
      return {
        ...state,
        entries: [...state.entries, action.entry],
        activity: { name: "sending", via: "text" },
        failure: null,
      };
    case "voice_sending":
      return { ...state, activity: { name: "sending", via: "voice" }, failure: null };
    case "replied": {
      const { reply, at, recognized } = action;
      const added: LogEntry[] = [];
      if (recognized) {
        added.push({
          kind: "user",
          key: recognized.key,
          text: recognized.text,
          createdAt: at,
          via: "voice",
          failed: false,
        });
      }
      added.push(assistantEntry(reply, at));
      const changed = reply.kind === "confirmation" || reply.undo !== null;
      return {
        ...state,
        entries: merge(state.entries, added),
        activity: { name: "idle" },
        failure: null,
        // Отменить можно только последнее действие: после нового изменения прежняя
        // кнопка вернула бы то, чего уже нет (сервер ответит «Отменить уже нельзя»).
        undoUntil:
          reply.undo && action.undoUntil !== null
            ? { [reply.message_id]: action.undoUntil }
            : changed
              ? {}
              : state.undoUntil,
        // Подсветка в плане — только сразу после изменения, следующий ответ её снимает.
        changedIds: changed ? reply.events.map((event) => event.id) : [],
      };
    }
    case "failed":
      return {
        ...state,
        entries: [
          ...state.entries.map((entry) =>
            entry.kind === "user" && entry.key === action.userKey
              ? { ...entry, failed: true }
              : entry,
          ),
          action.notice,
        ],
        activity: { name: "idle" },
        failure: action.failure,
      };
    case "notice":
      return {
        ...state,
        entries: [...state.entries, action.notice],
        failure: action.failure ?? state.failure,
      };
    case "undo_started":
      return { ...state, undoUntil: withoutKey(state.undoUntil, action.messageId) };
    case "undo_expired":
      return { ...state, undoUntil: withoutKey(state.undoUntil, action.messageId) };
    case "clear_failure":
      return state.failure === null ? state : { ...state, failure: null };
  }
}

/**
 * Чего ассистент ждёт от пользователя: вопрос последней реплики ассистента, если после
 * неё пользователь ничего не сказал. Строки об ошибках и неотвеченные реплики не в счёт —
 * вопрос на сервере остаётся в силе.
 */
export function pendingOf(entries: LogEntry[]): Pending | null {
  for (let index = entries.length - 1; index >= 0; index -= 1) {
    const entry = entries[index];
    if (!entry || entry.kind === "notice") continue;
    if (entry.kind === "user") {
      if (entry.failed) continue;
      return null;
    }
    return entry.reply?.pending ?? null;
  }
  return null;
}

/** Ключ последней реплики ассистента с вопросом — только у неё активны кнопки ответа. */
export function activeReplyKey(entries: LogEntry[]): string | null {
  for (let index = entries.length - 1; index >= 0; index -= 1) {
    const entry = entries[index];
    if (!entry || entry.kind === "notice") continue;
    if (entry.kind === "user") {
      if (entry.failed) continue;
      return null;
    }
    return entry.reply?.pending ? entry.key : null;
  }
  return null;
}
