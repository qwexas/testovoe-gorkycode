import type { AssistantReply, CalendarEvent, ChatMessage } from "@/types/api";

/** Состояния, которые можно открыть из демо-панели или параметром `?state=`. */
export const DEMO_STATE_IDS = [
  "idle",
  "recording",
  "processing",
  "confirmation",
  "list",
  "clarification",
  "choice",
  "search",
  "confirm-delete",
  "error",
] as const;

export type DemoStateId = (typeof DEMO_STATE_IDS)[number];

export function isDemoStateId(value: unknown): value is DemoStateId {
  return typeof value === "string" && (DEMO_STATE_IDS as readonly string[]).includes(value);
}

/** Реплика в истории: форма ChatMessage из контракта плюс то, что знает только фронт. */
export type DemoMessage = ChatMessage & {
  /** Как пользователь обратился: голосом или текстом. */
  via?: "voice" | "text";
  /** Ошибка запроса (например, `speech_not_recognized`), показанная репликой в логе. */
  failure?: "speech_not_recognized";
  /** Пришла в ответ на действие на этой странице (не из готового состояния) — можно анимировать. */
  live?: boolean;
};

/** Фаза разговора — то, что происходит прямо сейчас. Ответы живут в истории. */
export type DemoPhase =
  | { name: "idle" }
  | { name: "recording"; startedAt: number; auto: boolean }
  | {
      name: "processing";
      stage: "recognizing" | "thinking";
      via: "voice" | "text";
      auto: boolean;
    }
  | { name: "error" };

/**
 * Режим сферы. Выводится из фазы и последнего ответа:
 * слушает → думает → отвечает → ждёт уточнения / ошибка / покой.
 */
export type SphereMode = "idle" | "listening" | "thinking" | "speaking" | "waiting" | "error";

export type { AssistantReply, CalendarEvent };
