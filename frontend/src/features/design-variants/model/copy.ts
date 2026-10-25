/** Тексты состояний и быстрые ответы — общие для всех вариантов, чтобы сравнивать только дизайн. */
import type { AssistantReply, DemoPhase, SphereMode } from "./types";

export type QuickReply = { label: string; text: string; tone?: "danger" | "neutral" };

/**
 * Быстрые ответы выводятся из `pending.expects` — в контракте их нет и не нужно:
 * время по умолчанию взято из решения Q31 (утром 9:00, днём 13:00, вечером 19:00).
 */
export function quickReplies(reply: AssistantReply | null | undefined): QuickReply[] {
  const expects = reply?.pending?.expects;
  if (expects === "time") {
    return [
      { label: "Утром, в 9:00", text: "Утром, в 9:00" },
      { label: "Днём, в 13:00", text: "Днём, в 13:00" },
      { label: "Вечером, в 19:00", text: "Вечером, в 19:00" },
    ];
  }
  if (expects === "confirm") {
    return [
      { label: "Удалить встречу", text: "Да, удали", tone: "danger" },
      { label: "Оставить", text: "Нет, оставь" },
    ];
  }
  return [];
}

const ORDINALS = ["Первую", "Вторую", "Третью", "Четвёртую", "Пятую"] as const;

/** Что «говорит» кнопка варианта в списке совпадений: «Вторую». */
export function choiceText(index: number): string {
  return ORDINALS[index - 1] ?? String(index);
}

/** Подсказка, что ответить можно и голосом. */
export function voiceHint(reply: AssistantReply | null | undefined): string | null {
  switch (reply?.pending?.expects) {
    case "time":
      return "Или назовите время: «в 16:30»";
    case "choice":
      return "Или скажите номер: «вторую»";
    case "confirm":
      return "Или скажите «да» или «нет»";
    default:
      return null;
  }
}

/** Короткий статус сферы для live-региона: озвучивается при смене режима. */
export function sphereStatus(mode: SphereMode, phase: DemoPhase): string {
  switch (mode) {
    case "listening":
      return "Слушаю";
    case "thinking":
      return phase.name === "processing" && phase.stage === "recognizing"
        ? "Распознаю речь"
        : "Разбираю запрос";
    case "speaking":
      return "Отвечаю";
    case "waiting":
      return "Жду вашего ответа";
    case "error":
      return "Не расслышал";
    case "idle":
      return "Готов слушать";
  }
}

export const ANSWER_SOUND_LABEL = "Озвучивать ответы";

/** Подсказки с фразами из ТЗ показываем в начале разговора, пока ассистент ничего не ждёт. */
export function showSuggestions(
  phase: DemoPhase,
  pending: AssistantReply["pending"] | null,
  messageCount: number,
): boolean {
  return phase.name === "idle" && pending === null && messageCount <= 2;
}
