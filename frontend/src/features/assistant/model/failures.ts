/**
 * подбираем текст ошибки и кнопки повтора для лога разговора
 */
import type { ApiError } from "@/lib/api/errors";

import type { FailureKind, NoticeAction, Via } from "./conversation";

export type FailureCopy = { text: string; kind: FailureKind; actions: NoticeAction[] };

const RECORD_AGAIN: NoticeAction[] = [{ type: "record" }, { type: "type" }];

function retryActions(via: Via, text: string | null): NoticeAction[] {
  if (via === "voice") return RECORD_AGAIN;
  return text ? [{ type: "resend", text }] : [];
}

/** ошибка POST /api/chat или /api/voice. `text` — что повторить для текстовой реплики. */
export function describeRequestFailure(
  error: ApiError,
  via: Via,
  text: string | null,
): FailureCopy {
  switch (error.code) {
    case "rate_limited": {
      const seconds = error.retryAfterSeconds;
      const wait = seconds ? `${Math.max(1, Math.ceil(seconds))} с` : "минуту";
      return {
        text: `Слишком много запросов подряд. Подождите ${wait} и повторите.`,
        kind: "busy",
        actions: retryActions(via, text),
      };
    }
    case "speech_not_recognized":
      return {
        text: "Не расслышал. Скажите ещё раз, ближе к микрофону, или напишите текстом.",
        kind: "not-heard",
        actions: RECORD_AGAIN,
      };
    case "audio_too_large":
      return {
        text: "Не расслышал: запись слишком длинная. Уложитесь в минуту или напишите текстом.",
        kind: "not-heard",
        actions: RECORD_AGAIN,
      };
    case "audio_unsupported":
      return {
        text: "Не расслышал: сервер не читает формат записи этого браузера. Напишите текстом.",
        kind: "not-heard",
        actions: [{ type: "type" }],
      };
    case "validation_error":
      // validation_error может относиться к дате в команде, а не к самой записи голоса
      return {
        text: error.message,
        kind: "error",
        actions: via === "voice" ? RECORD_AGAIN : [],
      };
    case "stt_unavailable":
      return {
        text: "Распознавание речи сейчас не работает. Напишите текстом — так я пойму.",
        kind: "unavailable",
        actions: [{ type: "type" }],
      };
    case "not_implemented":
      return via === "voice"
        ? {
            text: "Голосовой ввод на сервере ещё не включён. Напишите текстом.",
            kind: "unavailable",
            actions: [{ type: "type" }],
          }
        : { text: error.message, kind: "unavailable", actions: [] };
    case "llm_unavailable":
      return { text: error.message, kind: "unavailable", actions: retryActions(via, text) };
    case "network_error":
      return {
        text: "Нет связи с сервером. Проверьте интернет и повторите.",
        kind: "offline",
        actions: retryActions(via, text),
      };
    case "server_unavailable":
      return { text: error.message, kind: "unavailable", actions: retryActions(via, text) };
    default:
      return { text: error.message, kind: "error", actions: retryActions(via, text) };
  }
}

/** ошибка отмены действия. */
export function describeUndoFailure(error: ApiError): FailureCopy {
  if (error.code === "not_found") {
    return { text: "Отменить уже нельзя: прошло больше 30 секунд.", kind: "error", actions: [] };
  }
  return describeRequestFailure(error, "text", null);
}
