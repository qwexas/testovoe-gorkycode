import type { DemoStateId } from "./types";

/** Подписи состояний для демо-панели — в порядке сценария разговора. */
export const DEMO_STATES: ReadonlyArray<{ id: DemoStateId; label: string }> = [
  { id: "idle", label: "Ожидание" },
  { id: "recording", label: "Запись" },
  { id: "processing", label: "Обработка" },
  { id: "confirmation", label: "Подтверждение с отменой" },
  { id: "list", label: "Список: что сегодня" },
  { id: "clarification", label: "Уточнение времени" },
  { id: "choice", label: "Выбор из совпадений" },
  { id: "search", label: "Результаты поиска" },
  { id: "confirm-delete", label: "Подтверждение удаления" },
  { id: "error", label: "Ошибка: не расслышал" },
];
