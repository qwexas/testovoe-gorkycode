"use client";

import { type RefObject, useState } from "react";

import { tty } from "@/components/ui/tty";
import { cn } from "@/lib/cn";
import { formatDuration } from "@/lib/format";

import { CHAT_TEXT_LIMIT } from "../api";
import type { Assistant } from "../hooks/use-assistant";
import { inputPlaceholder } from "../model/quick-replies";

const PROMPT_INPUT_ID = "prompt-input";

/** Строка `$`: ввод текстом, отправка Enter, кнопка «говорить» / «остановить». */
export function PromptLine({
  assistant,
  inputRef,
}: {
  assistant: Assistant;
  inputRef: RefObject<HTMLInputElement | null>;
}) {
  const [draft, setDraft] = useState("");
  const recording = assistant.recorder.status === "recording";
  const starting = assistant.recorder.status === "starting";
  const busy = assistant.sending;

  return (
    <form
      aria-label="Сообщение для Горького"
      className={cn(tty.promptRow, "flex min-h-14 items-center gap-2 px-3 py-2 sm:gap-3")}
      onSubmit={(event) => {
        event.preventDefault();
        if (busy || !draft.trim()) return;
        assistant.sendText(draft);
        setDraft("");
      }}
    >
      <span className={tty.prompt} aria-hidden="true">
        $
      </span>
      {recording ? (
        <div className="flex min-w-0 flex-1 flex-wrap items-center gap-x-3 gap-y-1">
          <span className={cn(tty.danger, tty.strong, "whitespace-nowrap")}>
            <span aria-hidden="true">● </span>
            <span className="max-sm:sr-only">запись </span>
            {formatDuration(assistant.recordingSeconds)}
          </span>
          <span className={cn(tty.muted, "text-xs max-sm:hidden")}>
            остановлюсь после паузы, Esc — отменить
          </span>
        </div>
      ) : null}
      <label htmlFor={PROMPT_INPUT_ID} className="sr-only">
        Сообщение для Горького
      </label>
      <input
        ref={inputRef}
        id={PROMPT_INPUT_ID}
        name="text"
        type="text"
        autoComplete="off"
        enterKeyHint="send"
        maxLength={CHAT_TEXT_LIMIT}
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
        placeholder={inputPlaceholder(assistant.pending)}
        hidden={recording}
        className={tty.input}
      />
      {recording ? (
        <button
          type="button"
          onClick={assistant.cancelRecording}
          className={cn(tty.btn, "whitespace-nowrap")}
        >
          <span className="max-sm:hidden">esc </span>отмена
        </button>
      ) : (
        <button
          type="submit"
          aria-disabled={busy || undefined}
          className={cn(tty.btn, "whitespace-nowrap", !draft && "max-sm:hidden")}
        >
          <span aria-hidden="true">⏎ </span>отправить
        </button>
      )}
      <button
        type="button"
        data-recording={recording || undefined}
        onClick={() => {
          if (busy && !recording) return;
          assistant.toggleRecording();
        }}
        aria-disabled={(busy && !recording) || undefined}
        className={cn(tty.mic, draft && !recording && "max-sm:hidden")}
      >
        <span className={tty.recDot} aria-hidden="true" />
        {recording ? "остановить" : starting ? "микрофон…" : "говорить"}
      </button>
    </form>
  );
}
