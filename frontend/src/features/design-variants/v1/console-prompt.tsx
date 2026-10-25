"use client";

import { type RefObject, useState } from "react";

import { cn } from "@/lib/cn";

import type { DemoAssistant } from "../hooks/use-demo-assistant";
import { useLevelMeter } from "../hooks/use-level-meter";
import { formatDuration } from "../model/format";
import { styles } from "./styles";

const BARS = " ▁▂▃▄▅▆▇█";
const METER_CELLS = 12;

/** Уровень голоса блочными символами: свежие значения справа. */
function applyMeter(element: HTMLElement, level: number) {
  const history = (element.dataset.history ?? "").split("").slice(-(METER_CELLS - 1));
  // Корень растягивает тихие уровни: речь в комнате редко доходит до максимума.
  const index = Math.min(BARS.length - 1, Math.round(Math.sqrt(level) * (BARS.length - 1)));
  history.push(BARS[index] ?? " ");
  const text = history.join("").padStart(METER_CELLS, " ");
  element.dataset.history = text;
  element.textContent = text;
}

/** Индикатор уровня голоса для панели сферы: обратная связь, что микрофон слышит. */
export function LevelMeter({ assistant }: { assistant: DemoAssistant }) {
  const recording = assistant.phase.name === "recording";
  const meterRef = useLevelMeter<HTMLSpanElement>(assistant.levelRef, recording, applyMeter);
  return (
    <p className={cn("flex items-baseline gap-3", !recording && "hidden")}>
      <span
        ref={meterRef}
        className={cn(styles.meter, "text-xl leading-none sm:text-2xl")}
        aria-hidden="true"
      />
      <span className={cn(styles.danger, styles.strong)}>
        {formatDuration(assistant.recordingSeconds)}
      </span>
    </p>
  );
}

export function ConsolePrompt({
  assistant,
  inputRef,
}: {
  assistant: DemoAssistant;
  inputRef: RefObject<HTMLInputElement | null>;
}) {
  const [draft, setDraft] = useState("");
  const recording = assistant.phase.name === "recording";
  const busy = assistant.phase.name === "processing";

  return (
    <form
      aria-label="Сообщение для Горького"
      className={cn(styles.promptRow, "flex min-h-14 items-center gap-2 px-3 py-2 sm:gap-3")}
      onSubmit={(event) => {
        event.preventDefault();
        if (busy) return;
        assistant.submitText(draft);
        setDraft("");
      }}
    >
      <span className={styles.prompt} aria-hidden="true">
        $
      </span>
      {recording ? (
        <div className="flex min-w-0 flex-1 flex-wrap items-center gap-x-3 gap-y-1">
          <span className={cn(styles.danger, styles.strong)}>
            ● запись {formatDuration(assistant.recordingSeconds)}
          </span>
          <span className={cn(styles.muted, "text-xs max-sm:hidden")}>Esc — отменить</span>
        </div>
      ) : null}
      <label htmlFor="v1-input" className="sr-only">
        Сообщение для Горького
      </label>
      <input
        ref={inputRef}
        id="v1-input"
        name="text"
        type="text"
        autoComplete="off"
        enterKeyHint="send"
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
        placeholder={
          assistant.pending?.expects === "time" ? "например, в 16:30" : "что у меня завтра?"
        }
        hidden={recording}
        className={styles.input}
      />
      {recording ? (
        <button
          type="button"
          onClick={assistant.cancelRecording}
          className={cn(styles.btn, "whitespace-nowrap")}
        >
          <span className="max-sm:hidden">esc </span>отмена
        </button>
      ) : (
        <button
          type="submit"
          aria-busy={busy || undefined}
          className={cn(styles.btn, "whitespace-nowrap", !draft && "max-sm:hidden")}
        >
          ⏎ отправить
        </button>
      )}
      <button
        type="button"
        data-recording={recording || undefined}
        onClick={() => {
          if (busy) return;
          if (recording) assistant.stopRecording();
          else assistant.startRecording();
        }}
        aria-disabled={busy || undefined}
        className={cn(
          styles.mic,
          "aria-disabled:cursor-progress aria-disabled:opacity-60",
          draft && !recording && "max-sm:hidden",
        )}
      >
        <span className={styles.recDot} aria-hidden="true" />
        {recording ? "остановить" : "говорить"}
      </button>
    </form>
  );
}
