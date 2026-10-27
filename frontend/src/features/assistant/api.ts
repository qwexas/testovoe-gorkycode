import { apiClient, unwrap } from "@/lib/api/client";
import { apiErrorFromException, apiErrorFromResponse } from "@/lib/api/errors";
import type { AssistantReply, ChatMessage } from "@/types/api";

/** Сервер принимает реплику до 1000 символов. */
export const CHAT_TEXT_LIMIT = 1000;
export const DIALOG_PAGE = 50;

/** Текстовая реплика. Реплика пользователя сохраняется в историю до разбора. */
export function sendChat(text: string): Promise<AssistantReply> {
  return unwrap(apiClient.POST("/api/chat", { body: { text } }));
}

/**
 * Голосовая реплика: multipart с полем `audio`. В ответе заполнен `recognized_text`.
 * Обычный fetch: тело — файл, а не JSON.
 */
export async function sendVoice(audio: Blob, fileName: string): Promise<AssistantReply> {
  const body = new FormData();
  body.append("audio", audio, fileName);
  let response: Response;
  try {
    response = await fetch("/api/voice", {
      method: "POST",
      body,
      credentials: "include",
      cache: "no-store",
    });
  } catch (cause) {
    throw apiErrorFromException(cause);
  }
  let data: unknown;
  try {
    data = await response.json();
  } catch (cause) {
    if (!response.ok) throw apiErrorFromResponse(response, null);
    throw apiErrorFromException(cause);
  }
  if (!response.ok) throw apiErrorFromResponse(response, data);
  return data as AssistantReply;
}

/** История диалога: последние `limit` реплик с id < beforeId, новые в конце. */
export async function fetchDialog(beforeId?: number): Promise<ChatMessage[]> {
  const { messages } = await unwrap(
    apiClient.GET("/api/dialog", {
      params: { query: { limit: DIALOG_PAGE, before_id: beforeId } },
      cache: "no-store",
    }),
  );
  return messages;
}

/** Отмена действия (сервер принимает 30 с). Позже или повторно — 404 «Отменить уже нельзя». */
export function undoAction(actionId: string): Promise<AssistantReply> {
  return unwrap(
    apiClient.POST("/api/actions/{action_id}/undo", { params: { path: { action_id: actionId } } }),
  );
}
