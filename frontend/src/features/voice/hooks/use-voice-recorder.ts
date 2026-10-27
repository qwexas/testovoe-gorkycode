"use client";

import { type RefObject, useCallback, useEffect, useRef, useState } from "react";

import {
  type Recording,
  RecorderError,
  type RecordingHandle,
  startRecording,
} from "../lib/recorder";

export type RecorderStatus =
  | { status: "idle" }
  /** Ждём разрешения на микрофон. */
  | { status: "starting" }
  | { status: "recording"; startedAt: number };

type Options = {
  onRecorded: (recording: Recording) => void;
  onError: (error: RecorderError) => void;
};

/**
 * Запись голоса для интерфейса: состояние, уровень голоса в ref (без перерисовки на
 * каждый кадр) и команды start / stop / cancel. При размонтировании запись отменяется.
 */
export function useVoiceRecorder(options: Options): {
  recorder: RecorderStatus;
  levelRef: RefObject<number>;
  start: () => Promise<void>;
  stop: () => void;
  cancel: () => void;
} {
  const [recorder, setRecorder] = useState<RecorderStatus>({ status: "idle" });
  const levelRef = useRef(0);
  const handleRef = useRef<RecordingHandle | null>(null);
  /** Номер текущей попытки: отменённая или устаревшая попытка не трогает состояние. */
  const attempt = useRef(0);
  const busyRef = useRef(false);
  const optionsRef = useRef(options);

  useEffect(() => {
    optionsRef.current = options;
  });

  const reset = useCallback(() => {
    handleRef.current = null;
    busyRef.current = false;
    levelRef.current = 0;
    setRecorder({ status: "idle" });
  }, []);

  const start = useCallback(async () => {
    if (busyRef.current) return;
    busyRef.current = true;
    attempt.current += 1;
    const current = attempt.current;
    setRecorder({ status: "starting" });
    try {
      const handle = await startRecording({
        onLevel: (level) => {
          if (current === attempt.current) levelRef.current = level;
        },
        onStop: (recording) => {
          if (current !== attempt.current) return;
          reset();
          optionsRef.current.onRecorded(recording);
        },
        onError: (error) => {
          if (current !== attempt.current) return;
          reset();
          optionsRef.current.onError(error);
        },
      });
      // Отменили (Esc или кнопка), пока браузер спрашивал разрешение на микрофон.
      if (current !== attempt.current) {
        handle.cancel();
        return;
      }
      handleRef.current = handle;
      setRecorder({ status: "recording", startedAt: performance.now() });
    } catch (cause) {
      if (current !== attempt.current) return;
      reset();
      optionsRef.current.onError(
        cause instanceof RecorderError ? cause : new RecorderError("failed", { cause }),
      );
    }
  }, [reset]);

  const stop = useCallback(() => handleRef.current?.stop(), []);

  const cancel = useCallback(() => {
    if (!busyRef.current) return;
    attempt.current += 1;
    handleRef.current?.cancel();
    reset();
  }, [reset]);

  useEffect(() => () => handleRef.current?.cancel(), []);

  return { recorder, levelRef, start, stop, cancel };
}
