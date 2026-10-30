"use client";

import { type RefObject, useCallback, useEffect, useMemo, useRef } from "react";

import { useSpeakPreference } from "@/features/voice/hooks/use-speak-preference";
import { useSpeech } from "@/features/voice/hooks/use-speech";
import { type RecorderStatus, useVoiceRecorder } from "@/features/voice/hooks/use-voice-recorder";
import { recordingFileName } from "@/features/voice/lib/recording-format";
import { useTicker } from "@/hooks/use-ticker";
import type { AssistantReply, Pending } from "@/types/api";

import {
  type ConversationState,
  type FailureKind,
  type NoticeEntry,
  activeReplyKey,
  pendingOf,
} from "../model/conversation";
import { describeRecorderError, rejectRecording } from "../model/microphone";
import { type SphereMode, sphereHeadline, sphereMode, sphereSubline } from "../model/sphere";
import { useConversation } from "./use-conversation";

/** горячая клавиша записи: Alt+M (⌥M) — свободна в Chrome, Safari и Firefox. */
function isRecordHotkey(event: KeyboardEvent): boolean {
  return event.altKey && !event.ctrlKey && !event.metaKey && event.code === "KeyM";
}

function changesEvents(reply: AssistantReply): boolean {
  return reply.kind === "confirmation" || reply.undo !== null;
}

export type Assistant = {
  conversation: ConversationState;
  pending: Pending | null;
  /** ключ реплики ассистента, на вопрос которой можно ответить кнопками. */
  activeKey: string | null;
  /** секунд до закрытия окна отмены по id реплики ассистента. */
  undoSecondsLeft: (messageId: number) => number | null;
  recorder: RecorderStatus;
  recordingSeconds: number;
  sending: boolean;
  speaking: boolean;
  sphere: SphereMode;
  headline: string;
  subline: string;
  /** уровень звука для сферы: голос пользователя при записи, ответ — при озвучке. */
  levelRef: RefObject<number>;
  speakReplies: boolean;
  setSpeakReplies: (value: boolean) => void;
  sendText: (text: string) => void;
  toggleRecording: () => void;
  cancelRecording: () => void;
  undo: (messageId: number, actionId: string) => void;
  loadOlder: () => void;
  reloadHistory: () => void;
  addNotice: (notice: NoticeEntry) => void;
};

/**
 * Esc отменяет запись или озвучку, Alt+M включает и выключает запись (Q26).
 */
export function useAssistant({
  profileId,
  onEventsChanged,
}: {
  profileId: string | null;
  onEventsChanged: () => void;
}): Assistant {
  const speech = useSpeech();
  const [speakReplies, setSpeakRepliesState] = useSpeakPreference();
  const speakRef = useRef(speakReplies);
  const onEventsChangedRef = useRef(onEventsChanged);

  useEffect(() => {
    speakRef.current = speakReplies;
    onEventsChangedRef.current = onEventsChanged;
  });

  const { speak, stop: stopSpeech } = speech;
  const onReply = useCallback(
    (reply: AssistantReply) => {
      if (speakRef.current) speak(reply.text);
      if (changesEvents(reply)) onEventsChangedRef.current();
    },
    [speak],
  );

  const conversation = useConversation({ profileId, onReply });
  const { sendRecording, addFailure, clearFailure, expireUndo } = conversation;

  const voice = useVoiceRecorder({
    onRecorded: (recording) => {
      const rejected = rejectRecording(recording);
      if (rejected) {
        addFailure(rejected);
        return;
      }
      void sendRecording(recording.blob, recordingFileName(recording.mimeType));
    },
    onError: (error) => addFailure(describeRecorderError(error.code)),
  });

  const { state } = conversation;
  const sending = state.activity.name === "sending";
  const micBusy = voice.recorder.status !== "idle";
  const micStarting = voice.recorder.status === "starting";

  const setSpeakReplies = useCallback(
    (value: boolean) => {
      setSpeakRepliesState(value);
      if (!value) stopSpeech();
    },
    [setSpeakRepliesState, stopSpeech],
  );

  const { start: startVoice, stop: stopVoice, cancel: cancelVoice } = voice;
  const toggleRecording = useCallback(() => {
    if (voice.recorder.status === "recording") {
      stopVoice();
      return;
    }
    // пока браузер спрашивает разрешение, повторное нажатие отменяет запуск.
    if (voice.recorder.status === "starting") {
      cancelVoice();
      return;
    }
    if (sending) return;
    if (!profileId) {
      addFailure({
        text: "Профиль ещё не готов. Дождитесь загрузки или создайте профиль в меню профиля внизу экрана.",
        kind: "error",
        actions: [],
      });
      return;
    }
    stopSpeech();
    clearFailure();
    void startVoice();
  }, [
    voice.recorder.status,
    sending,
    profileId,
    stopVoice,
    cancelVoice,
    stopSpeech,
    clearFailure,
    startVoice,
    addFailure,
  ]);

  const { sendText: sendConversationText } = conversation;
  const sendText = useCallback(
    (text: string) => {
      stopSpeech();
      void sendConversationText(text);
    },
    [stopSpeech, sendConversationText],
  );

  // Esc — отменить запись или замолчать; Alt+M — начать или закончить запись.
  const recordingRef = useRef(micBusy);
  const speakingRef = useRef(speech.speaking);
  useEffect(() => {
    recordingRef.current = micBusy;
    speakingRef.current = speech.speaking;
  });
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        if (recordingRef.current) {
          event.preventDefault();
          cancelVoice();
        } else if (speakingRef.current) {
          stopSpeech();
        }
        return;
      }
      if (isRecordHotkey(event) && !event.repeat) {
        event.preventDefault();
        toggleRecording();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [cancelVoice, stopSpeech, toggleRecording]);

  // часы для окна отмены и длительности записи: тикают, только пока это нужно.
  const undoOpen = Object.keys(state.undoUntil).length > 0;
  const clock = useTicker(undoOpen || voice.recorder.status === "recording", 250);

  useEffect(() => {
    for (const [id, until] of Object.entries(state.undoUntil)) {
      if (clock >= until) expireUndo(Number(id));
    }
  }, [clock, state.undoUntil, expireUndo]);

  const undoSecondsLeft = useCallback(
    (messageId: number) => {
      const until = state.undoUntil[messageId];
      if (until === undefined) return null;
      return Math.max(0, Math.ceil((until - clock) / 1000));
    },
    [state.undoUntil, clock],
  );

  const pending = useMemo(() => pendingOf(state.entries), [state.entries]);
  const activeKey = useMemo(() => activeReplyKey(state.entries), [state.entries]);
  const failure: FailureKind | null = state.failure;
  const mode = sphereMode({
    recording: voice.recorder.status === "recording",
    sending,
    speaking: speech.speaking,
    waiting: pending !== null,
    failure,
  });
  const via = state.activity.name === "sending" ? state.activity.via : null;

  const recordingSeconds =
    voice.recorder.status === "recording"
      ? Math.max(0, (clock - voice.recorder.startedAt) / 1000)
      : 0;

  const { undo: undoConversation, loadOlder, reloadHistory, addNotice } = conversation;

  return {
    conversation: state,
    pending,
    activeKey,
    undoSecondsLeft,
    recorder: voice.recorder,
    recordingSeconds,
    sending,
    speaking: speech.speaking,
    sphere: mode,
    headline: micStarting ? "включаю микрофон" : sphereHeadline(mode, failure, via),
    subline: micStarting
      ? "если браузер спросит — разрешите доступ к микрофону; Esc — отмена"
      : sphereSubline(mode, failure),
    levelRef: mode === "speaking" ? speech.levelRef : voice.levelRef,
    speakReplies,
    setSpeakReplies,
    sendText,
    toggleRecording,
    cancelRecording: cancelVoice,
    undo: (messageId, actionId) => void undoConversation(messageId, actionId),
    loadOlder: () => void loadOlder(),
    reloadHistory,
    addNotice,
  };
}
