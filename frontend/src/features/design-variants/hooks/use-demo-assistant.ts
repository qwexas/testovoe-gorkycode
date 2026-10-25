"use client";

import { type RefObject, useCallback, useEffect, useMemo, useReducer, useState } from "react";

import {
  type Conversation,
  assistantMessage,
  buildPreset,
  failureMessage,
  pendingOf,
  respond,
  simulatedRecognition,
  undoLast,
  userMessage,
} from "../model/conversation";
import { DEMO_NOW_ISO } from "../model/mock-data";
import type { DemoMessage, DemoPhase, DemoStateId, SphereMode } from "../model/types";

export { DEMO_STATES } from "../model/states";
import { useSimulatedLevel } from "./use-simulated-level";

const UNDO_WINDOW_MS = 10_000;
/** Демо-автостоп: в продукте запись останавливается после ~1,2 с тишины (решение Q26). */
const AUTO_STOP_MS = 4_200;
const RECOGNIZE_MS = 900;
const THINK_MS = 800;
const MIN_SPEECH_MS = 1_200;

type Model = Conversation & {
  phase: DemoPhase;
  undoUntil: number | null;
  speakingUntil: number | null;
  preset: DemoStateId | null;
};

type Action =
  | { type: "jump"; id: DemoStateId; now: number }
  | { type: "startRecording"; now: number }
  | { type: "cancelRecording" }
  | { type: "stopRecording"; now: number }
  | { type: "recognized"; text: string }
  | { type: "submitText"; text: string }
  | { type: "reply"; now: number; speak: boolean }
  | { type: "undo" }
  | { type: "undoExpired" }
  | { type: "speakingDone" };

function fromPreset(id: DemoStateId, now: number): Model {
  const preset = buildPreset(id, now);
  return {
    messages: preset.messages,
    feed: preset.feed,
    phase: preset.phase,
    undoUntil: preset.undoOpen ? now + UNDO_WINDOW_MS : null,
    speakingUntil: null,
    preset: id,
  };
}

function speakingTime(text: string): number {
  return Math.min(4_500, Math.max(1_500, text.length * 55));
}

function failWith(model: Model): Model {
  return {
    ...model,
    messages: [...model.messages, { ...failureMessage(DEMO_NOW_ISO), live: true }],
    phase: { name: "error" },
  };
}

function reducer(model: Model, action: Action): Model {
  switch (action.type) {
    case "jump":
      return fromPreset(action.id, action.now);
    case "startRecording":
      if (model.phase.name === "processing") return model;
      return {
        ...model,
        phase: { name: "recording", startedAt: action.now, auto: true },
        undoUntil: null,
        speakingUntil: null,
        preset: null,
      };
    case "cancelRecording":
      return model.phase.name === "recording" ? { ...model, phase: { name: "idle" } } : model;
    case "stopRecording":
      if (model.phase.name !== "recording") return model;
      // Слишком короткая запись — как `speech_not_recognized` от сервера.
      if (action.now - model.phase.startedAt < MIN_SPEECH_MS) return failWith(model);
      return {
        ...model,
        phase: { name: "processing", stage: "recognizing", via: "voice", auto: true },
        preset: null,
      };
    case "recognized":
      return {
        ...model,
        messages: [...model.messages, userMessage(action.text, DEMO_NOW_ISO, "voice")],
        phase: { name: "processing", stage: "thinking", via: "voice", auto: true },
      };
    case "submitText": {
      if (model.phase.name === "processing") return model;
      return {
        ...model,
        messages: [...model.messages, userMessage(action.text, DEMO_NOW_ISO, "text")],
        phase: { name: "processing", stage: "thinking", via: "text", auto: true },
        undoUntil: null,
        speakingUntil: null,
        preset: null,
      };
    }
    case "reply": {
      const lastUser = [...model.messages].reverse().find((message) => message.role === "user");
      // Ответ даётся на последнюю реплику пользователя; уточнение берётся из реплики перед ней.
      const context = { messages: model.messages.slice(0, -1), feed: model.feed };
      const { reply, feed } = respond(lastUser?.text ?? "", context);
      return {
        messages: [...model.messages, { ...assistantMessage(reply, DEMO_NOW_ISO), live: true }],
        feed,
        phase: { name: "idle" },
        undoUntil: reply.undo ? action.now + UNDO_WINDOW_MS : null,
        speakingUntil: action.speak ? action.now + speakingTime(reply.text) : null,
        preset: null,
      };
    }
    case "undo":
      if (model.undoUntil === null) return model;
      return { ...model, ...undoLast(model), undoUntil: null, preset: null };
    case "undoExpired":
      return { ...model, undoUntil: null };
    case "speakingDone":
      return { ...model, speakingUntil: null };
  }
}

export type DemoAssistant = {
  preset: DemoStateId | null;
  phase: DemoPhase;
  messages: DemoMessage[];
  feed: Conversation["feed"];
  sphere: SphereMode;
  /** Уровень голоса 0..1 для сферы и индикатора записи (симуляция). */
  levelRef: RefObject<number>;
  /** Последняя реплика ассистента ждёт ответа (уточнение, выбор, подтверждение). */
  pending: ReturnType<typeof pendingOf>;
  /** Секунд до закрытия окна отмены; null — отменять нечего. */
  undoSecondsLeft: number | null;
  recordingSeconds: number;
  soundOn: boolean;
  setSoundOn: (value: boolean) => void;
  jump: (id: DemoStateId) => void;
  startRecording: () => void;
  stopRecording: () => void;
  cancelRecording: () => void;
  submitText: (text: string) => void;
  undo: () => void;
};

/**
 * Машина состояний демо-разговора. Переходы: ожидание → запись → распознавание →
 * разбор → ответ (подтверждение / список / уточнение / выбор / удаление) → ожидание;
 * ошибка распознавания — из записи. Готовые состояния (`jump`) не идут дальше сами.
 */
export function useDemoAssistant(initial: DemoStateId): DemoAssistant {
  const [model, dispatch] = useReducer(reducer, initial, (id) => fromPreset(id, performance.now()));
  const [soundOn, setSoundOn] = useState(true);
  const [clock, setClock] = useState(() => performance.now());

  const { phase } = model;

  // Автостоп записи (в продукте — после тишины), потом распознавание и разбор.
  useEffect(() => {
    if (phase.name === "recording" && phase.auto) {
      const timer = window.setTimeout(
        () => dispatch({ type: "stopRecording", now: performance.now() }),
        AUTO_STOP_MS,
      );
      return () => window.clearTimeout(timer);
    }
    if (phase.name === "processing" && phase.auto) {
      const timer = window.setTimeout(
        () => {
          if (phase.stage === "recognizing") {
            dispatch({ type: "recognized", text: simulatedRecognition(model.messages) });
          } else {
            dispatch({ type: "reply", now: performance.now(), speak: soundOn });
          }
        },
        phase.stage === "recognizing" ? RECOGNIZE_MS : THINK_MS,
      );
      return () => window.clearTimeout(timer);
    }
    return undefined;
  }, [phase, model.messages, soundOn]);

  // Часы для таймера записи и окна отмены: тикают, только пока это нужно.
  const ticking = phase.name === "recording" || model.undoUntil !== null;
  useEffect(() => {
    if (!ticking) return undefined;
    const interval = window.setInterval(() => setClock(performance.now()), 250);
    return () => window.clearInterval(interval);
  }, [ticking]);

  useEffect(() => {
    if (model.undoUntil !== null && clock >= model.undoUntil) dispatch({ type: "undoExpired" });
  }, [clock, model.undoUntil]);

  useEffect(() => {
    if (model.speakingUntil === null) return undefined;
    const timer = window.setTimeout(
      () => dispatch({ type: "speakingDone" }),
      Math.max(0, model.speakingUntil - performance.now()),
    );
    return () => window.clearTimeout(timer);
  }, [model.speakingUntil]);

  // Esc отменяет запись (решение Q26).
  useEffect(() => {
    if (phase.name !== "recording") return undefined;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") dispatch({ type: "cancelRecording" });
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [phase.name]);

  const pending = pendingOf(model.messages);

  const sphere: SphereMode = useMemo(() => {
    if (phase.name === "recording") return "listening";
    if (phase.name === "processing") return "thinking";
    if (phase.name === "error") return "error";
    if (model.speakingUntil !== null) return "speaking";
    if (pending) return "waiting";
    return "idle";
  }, [phase.name, model.speakingUntil, pending]);

  const levelRef = useSimulatedLevel(sphere);

  const jump = useCallback(
    (id: DemoStateId) => dispatch({ type: "jump", id, now: performance.now() }),
    [],
  );
  const startRecording = useCallback(
    () => dispatch({ type: "startRecording", now: performance.now() }),
    [],
  );
  const stopRecording = useCallback(
    () => dispatch({ type: "stopRecording", now: performance.now() }),
    [],
  );
  const cancelRecording = useCallback(() => dispatch({ type: "cancelRecording" }), []);
  const submitText = useCallback((text: string) => {
    const trimmed = text.trim();
    if (trimmed) dispatch({ type: "submitText", text: trimmed });
  }, []);
  const undo = useCallback(() => dispatch({ type: "undo" }), []);

  const recordingSeconds =
    phase.name === "recording" ? Math.max(0, (clock - phase.startedAt) / 1000) : 0;
  const undoSecondsLeft =
    model.undoUntil === null ? null : Math.max(0, Math.ceil((model.undoUntil - clock) / 1000));

  return {
    preset: model.preset,
    phase,
    messages: model.messages,
    feed: model.feed,
    sphere,
    levelRef,
    pending,
    undoSecondsLeft,
    recordingSeconds,
    soundOn,
    setSoundOn,
    jump,
    startRecording,
    stopRecording,
    cancelRecording,
    submitText,
    undo,
  };
}
