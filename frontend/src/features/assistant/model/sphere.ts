/** режим сферы и подписи к нему. Режим выводится из записи, запроса, озвучки и вопроса. */
import type { FailureKind, Via } from "./conversation";

/** слушает → думает → отвечает → ждёт ответа / ошибка / покой. */
export type SphereMode = "idle" | "listening" | "thinking" | "speaking" | "waiting" | "error";

export function sphereMode(input: {
  recording: boolean;
  sending: boolean;
  speaking: boolean;
  waiting: boolean;
  failure: FailureKind | null;
}): SphereMode {
  if (input.recording) return "listening";
  if (input.sending) return "thinking";
  if (input.speaking) return "speaking";
  if (input.failure) return "error";
  if (input.waiting) return "waiting";
  return "idle";
}

const FAILURE_HEADLINES: Record<FailureKind, string> = {
  "not-heard": "не расслышал",
  microphone: "нет микрофона",
  offline: "нет связи",
  busy: "подождите",
  unavailable: "сервис недоступен",
  error: "не получилось",
};

/** крупная строка состояния (она же — live-регион для экранного диктора). */
export function sphereHeadline(
  mode: SphereMode,
  failure: FailureKind | null,
  via: Via | null,
): string {
  switch (mode) {
    case "listening":
      return "слушаю";
    case "thinking":
      return via === "voice" ? "распознаю речь" : "разбираю запрос";
    case "speaking":
      return "отвечаю";
    case "waiting":
      return "жду вашего ответа";
    case "error":
      return FAILURE_HEADLINES[failure ?? "error"];
    case "idle":
      return "готов слушать";
  }
}

/** подсказка под строкой состояния: что можно сделать сейчас. */
export function sphereSubline(mode: SphereMode, failure: FailureKind | null): string {
  switch (mode) {
    case "listening":
      return "говорите — остановлюсь сам после паузы";
    case "thinking":
      return "секунду";
    case "speaking":
      return "озвучку можно выключить внизу экрана, Esc — замолчать";
    case "waiting":
      return "ответьте голосом, текстом или кнопкой";
    case "error":
      return failure === "busy" || failure === "offline" || failure === "unavailable"
        ? "подробности — в строке сессии"
        : "запишите ещё раз или напишите текстом";
    case "idle":
      return "нажмите «говорить» или пишите в строке ниже";
  }
}
