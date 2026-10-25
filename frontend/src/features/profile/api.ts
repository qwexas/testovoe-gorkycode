import { apiClient, unwrap } from "@/lib/api/client";
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
