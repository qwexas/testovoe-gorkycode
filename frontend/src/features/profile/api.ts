import { apiClient, unwrap } from "@/lib/api/client";
import { apiErrorFromException, apiErrorFromResponse } from "@/lib/api/errors";
import type { Profile } from "@/types/api";

/** Текущий профиль. Если cookie нет, сервер создаёт профиль и возвращает recovery_code. */
export function fetchCurrentProfile(): Promise<Profile> {
  return unwrap(apiClient.GET("/api/me", { cache: "no-store" }));
}

/** «Новый профиль»: сервер создаёт профиль и переключает cookie. */
export function createProfile(): Promise<Profile> {
  return unwrap(apiClient.POST("/api/profiles"));
}

/** Вход по коду восстановления. Ошибки: invalid_recovery_code, rate_limited. */
export function restoreProfile(code: string): Promise<Profile> {
  return unwrap(apiClient.POST("/api/profiles/restore", { body: { code } }));
}

/** «Удалить все мои данные»: профиль, записи и диалог; cookie сбрасывается. */
export async function deleteCurrentProfile(): Promise<void> {
  await unwrap(apiClient.DELETE("/api/me"));
}

/**
 * Календарь профиля одним файлом (GET /api/calendar.ics). Скачиваем через fetch, а не
 * ссылкой: так ошибку сервера можно показать текстом, а не сохранить вместо календаря.
 */
export const CALENDAR_FILE_NAME = "gorky.ics";

export async function downloadCalendar(): Promise<void> {
  let response: Response;
  try {
    response = await fetch("/api/calendar.ics", { credentials: "include", cache: "no-store" });
  } catch (cause) {
    throw apiErrorFromException(cause);
  }
  if (!response.ok) {
    const body: unknown = await response.json().catch(() => null);
    throw apiErrorFromResponse(response, body);
  }
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement("a");
  link.href = url;
  link.download = CALENDAR_FILE_NAME;
  document.body.append(link);
  link.click();
  link.remove();
  // Даём браузеру начать загрузку, прежде чем освободить ссылку на файл.
  window.setTimeout(() => URL.revokeObjectURL(url), 10_000);
}
