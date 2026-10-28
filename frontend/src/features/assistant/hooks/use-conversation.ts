"use client";

import { useCallback, useEffect, useReducer, useRef } from "react";

import { apiErrorFromException } from "@/lib/api/errors";
import type { AssistantReply } from "@/types/api";

import { CHAT_TEXT_LIMIT, DIALOG_PAGE, fetchDialog, sendChat, sendVoice, undoAction } from "../api";
import {
  type ConversationState,
  type NoticeEntry,
  conversationReducer,
  createNotice,
  initialConversation,
  localKey,
} from "../model/conversation";
import { type FailureCopy, describeRequestFailure, describeUndoFailure } from "../model/failures";

/** Кнопку «Отменить» показываем 10 с (решение Q33); сервер принимает отмену 30 с. */
export const UNDO_WINDOW_MS = 10_000;

function nowIso(): string {
  return new Date().toISOString();
}

type Options = {
  /** null — профиля нет или он ещё грузится: история не запрашивается, отправлять нельзя. */
  profileId: string | null;
  /** Каждый новый ответ ассистента (для озвучки и обновления плана дня). */
  onReply: (reply: AssistantReply, via: "voice" | "text" | "undo") => void;
};

export type Conversation = {
  state: ConversationState;
  sendText: (text: string) => Promise<void>;
  sendRecording: (audio: Blob, fileName: string) => Promise<void>;
  undo: (messageId: number, actionId: string) => Promise<void>;
  loadOlder: () => Promise<void>;
  reloadHistory: () => void;
  addFailure: (copy: FailureCopy) => void;
  addNotice: (notice: NoticeEntry) => void;
  expireUndo: (messageId: number) => void;
  clearFailure: () => void;
};

/**
 * Разговор с сервером: история (GET /api/dialog), реплики текстом и голосом
 * (POST /api/chat, /api/voice) и отмена (POST /api/actions/{id}/undo). Ошибки не
 * роняют экран, а становятся строками лога с подсказкой, что делать.
 */
export function useConversation({ profileId, onReply }: Options): Conversation {
  const [state, dispatch] = useReducer(conversationReducer, initialConversation);
  const onReplyRef = useRef(onReply);
  const profileRef = useRef(profileId);
  const sendingRef = useRef(false);
  const [historyVersion, bumpHistory] = useReducer((value: number) => value + 1, 0);
  const firstId = useRef<number | null>(null);

  useEffect(() => {
    onReplyRef.current = onReply;
    profileRef.current = profileId;
  });

  useEffect(() => {
    const first = state.entries.find((entry) => entry.key.startsWith("m"));
    firstId.current = first ? Number(first.key.slice(1)) : null;
  }, [state.entries]);

  // История — только после того, как профиль пришёл из GET /api/me (контракт API).
  useEffect(() => {
    if (!profileId) return undefined;
    let cancelled = false;
    fetchDialog().then(
      (messages) => {
        if (cancelled) return;
        dispatch({
          type: "history_loaded",
          profileId,
          messages,
          hasOlder: messages.length >= DIALOG_PAGE,
        });
      },
      () => {
        if (!cancelled) dispatch({ type: "history_failed", profileId });
      },
    );
    return () => {
      cancelled = true;
    };
  }, [profileId, historyVersion]);

  const fail = useCallback((owner: string, copy: FailureCopy, userKey?: string) => {
    dispatch({
      type: "failed",
      profileId: owner,
      notice: createNotice(copy.text, "error", copy.actions),
      failure: copy.kind,
      userKey,
    });
  }, []);

  const notReady = useCallback(() => {
    dispatch({
      type: "notice",
      notice: createNotice(
        "Профиль ещё не готов. Дождитесь загрузки или создайте профиль в меню профиля внизу экрана.",
      ),
    });
  }, []);

  const sendText = useCallback(
    async (raw: string) => {
      const text = raw.trim().slice(0, CHAT_TEXT_LIMIT);
      if (!text || sendingRef.current) return;
      if (!profileId) {
        notReady();
        return;
      }
      sendingRef.current = true;
      const key = localKey("user");
      dispatch({
        type: "user_sent",
        entry: { kind: "user", key, text, createdAt: nowIso(), via: "text", failed: false },
      });
      try {
        const reply = await sendChat(text);
        dispatch({
          type: "replied",
          profileId,
          reply,
          at: nowIso(),
          undoUntil: reply.undo ? performance.now() + UNDO_WINDOW_MS : null,
        });
        if (profileRef.current === profileId) onReplyRef.current(reply, "text");
      } catch (cause) {
        fail(profileId, describeRequestFailure(apiErrorFromException(cause), "text", text), key);
      } finally {
        sendingRef.current = false;
      }
    },
    [profileId, fail, notReady],
  );

  const sendRecording = useCallback(
    async (audio: Blob, fileName: string) => {
      if (sendingRef.current) return;
      if (!profileId) {
        notReady();
        return;
      }
      sendingRef.current = true;
      dispatch({ type: "voice_sending" });
      try {
        const reply = await sendVoice(audio, fileName);
        const recognized = reply.recognized_text?.trim();
        dispatch({
          type: "replied",
          profileId,
          reply,
          at: nowIso(),
          recognized: recognized ? { key: localKey("voice"), text: recognized } : undefined,
          undoUntil: reply.undo ? performance.now() + UNDO_WINDOW_MS : null,
        });
        if (profileRef.current === profileId) onReplyRef.current(reply, "voice");
      } catch (cause) {
        fail(profileId, describeRequestFailure(apiErrorFromException(cause), "voice", null));
      } finally {
        sendingRef.current = false;
      }
    },
    [profileId, fail, notReady],
  );

  const undo = useCallback(
    async (messageId: number, actionId: string) => {
      dispatch({ type: "undo_started", messageId });
      try {
        const reply = await undoAction(actionId);
        dispatch({ type: "replied", profileId, reply, at: nowIso(), undoUntil: null });
        if (profileRef.current === profileId) onReplyRef.current(reply, "undo");
      } catch (cause) {
        const copy = describeUndoFailure(apiErrorFromException(cause));
        dispatch({
          type: "notice",
          notice: createNotice(copy.text, "error", copy.actions),
          failure: copy.kind,
        });
      }
    },
    [profileId],
  );

  const loadOlder = useCallback(async () => {
    const beforeId = firstId.current;
    if (beforeId === null) return;
    dispatch({ type: "older_loading" });
    try {
      const messages = await fetchDialog(beforeId);
      dispatch({
        type: "older_loaded",
        profileId,
        messages,
        hasOlder: messages.length >= DIALOG_PAGE,
      });
    } catch (cause) {
      dispatch({ type: "older_failed" });
      const error = apiErrorFromException(cause);
      dispatch({
        type: "notice",
        notice: createNotice(`Более ранние реплики не загрузились. ${error.message}`),
      });
    }
  }, [profileId]);

  const addFailure = useCallback((copy: FailureCopy) => {
    dispatch({
      type: "notice",
      notice: createNotice(copy.text, "error", copy.actions),
      failure: copy.kind,
    });
  }, []);

  const addNotice = useCallback((notice: NoticeEntry) => dispatch({ type: "notice", notice }), []);

  const expireUndo = useCallback(
    (messageId: number) => dispatch({ type: "undo_expired", messageId }),
    [],
  );
  const clearFailure = useCallback(() => dispatch({ type: "clear_failure" }), []);

  // Пока история нового профиля не пришла, прежняя не показывается.
  const view: ConversationState =
    state.profileId === profileId ? state : { ...initialConversation, profileId };

  return {
    state: view,
    sendText,
    sendRecording,
    undo,
    loadOlder,
    reloadHistory: bumpHistory,
    addFailure,
    addNotice,
    expireUndo,
    clearFailure,
  };
}
