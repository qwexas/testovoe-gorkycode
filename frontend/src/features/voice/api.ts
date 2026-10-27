import { apiErrorFromException, apiErrorFromResponse } from "@/lib/api/errors";

/** Сервер озвучивает до 1000 символов за раз. */
export const SPEECH_TEXT_LIMIT = 1000;

/**
 * Озвучка ответа Silero (POST /api/tts) → аудио OGG/Opus. Бинарный ответ, поэтому
 * обычный fetch, а не JSON-клиент; ошибки — те же ApiError, что у остального API.
 */
export async function fetchSpeech(text: string, signal?: AbortSignal): Promise<Blob> {
  let response: Response;
  try {
    response = await fetch("/api/tts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: text.slice(0, SPEECH_TEXT_LIMIT) }),
      credentials: "include",
      cache: "no-store",
      signal,
    });
  } catch (cause) {
    throw apiErrorFromException(cause);
  }
  if (!response.ok) {
    const body: unknown = await response.json().catch(() => null);
    throw apiErrorFromResponse(response, body);
  }
  return response.blob();
}
