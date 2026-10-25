"use client";

import { useEffect, useState } from "react";

import { cn } from "@/lib/cn";

import type { DemoAssistant } from "../hooks/use-demo-assistant";
import { choiceText, quickReplies, showSuggestions, voiceHint } from "../model/copy";
import { EXAMPLE_PHRASES } from "../model/mock-data";
import {
  TYPE_LABELS,
  eventTiming,
  formatDayLabel,
  formatEventTime,
  formatTime,
  formatWhen,
} from "../model/format";
import type { CalendarEvent, DemoMessage } from "../model/types";
import { PixelGlyph, eventGlyph } from "./pixel-glyphs";

const TYPE_MS = 16;

/**
 * Текст «печатается», как реплика в RPG, — только у нового ответа и без reduced motion.
 * Экранный диктор получает полный текст сразу (видимая анимация скрыта от него).
 */
function TypedText({ text, animate }: { text: string; animate: boolean }) {
  const [shown, setShown] = useState(() =>
    animate && !window.matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : text.length,
  );

  useEffect(() => {
    if (shown >= text.length) return undefined;
    const timer = window.setTimeout(() => setShown((value) => value + 1), TYPE_MS);
    return () => window.clearTimeout(timer);
  }, [shown, text.length]);

  return (
    <>
      <span aria-hidden="true">
        {text.slice(0, shown)}
        <span className="invisible">{text.slice(shown)}</span>
      </span>
      <span className="sr-only">{text}</span>
    </>
  );
}

function EventRows({ events, withDate }: { events: CalendarEvent[]; withDate?: boolean }) {
  return (
    <ul className="v3-inset mt-3 grid gap-px py-1">
      {events.map((event) => {
        const done = eventTiming(event) === "done";
        return (
          <li
            key={event.id}
            className={cn(
              "grid items-baseline gap-x-2.5 px-3 py-1.5",
              withDate ? "grid-cols-[auto_minmax(0,1fr)]" : "grid-cols-[auto_auto_minmax(0,1fr)]",
            )}
          >
            {withDate ? null : (
              <span className="v3-pixel w-[3.75rem] text-[1.25rem] leading-tight">
                {formatEventTime(event)}
              </span>
            )}
            <PixelGlyph
              name={eventGlyph(event)}
              size={12}
              className={cn(
                "translate-y-[1px] self-center",
                event.type === "meeting" ? "v3-accent" : "v3-wait",
              )}
            />
            <span className={cn("min-w-0", done && !withDate && "v3-muted line-through")}>
              {event.title}
              <span className="v3-muted block text-sm">
                {TYPE_LABELS[event.type]}
                {withDate && event.starts_at ? `, ${formatDayLabel(event.starts_at)}` : ""}
                {done ? ", выполнено" : ""}
              </span>
            </span>
          </li>
        );
      })}
    </ul>
  );
}

function UndoBar({ seconds, onUndo }: { seconds: number; onUndo: () => void }) {
  return (
    <div className="mt-3 flex flex-wrap items-center gap-3">
      <button type="button" onClick={onUndo} className="v3-btn">
        Отменить
      </button>
      <span className="flex h-4 gap-1" aria-hidden="true">
        {Array.from({ length: 10 }, (_, index) => (
          <span key={index} className="v3-seg" data-on={index < seconds || undefined} />
        ))}
      </span>
      <span className="v3-muted text-sm">ещё {seconds} с</span>
    </div>
  );
}

function GorkyLine({
  message,
  latest,
  active,
  fresh,
  assistant,
  onFocusInput,
}: {
  message: DemoMessage;
  latest: boolean;
  active: boolean;
  fresh: boolean;
  assistant: DemoAssistant;
  onFocusInput: () => void;
}) {
  if (message.failure) {
    return (
      <div>
        <p className={cn("v3-say v3-danger", latest && "v3-sayLatest")}>
          <TypedText text={message.text} animate={fresh} />
        </p>
        {latest ? (
          <div className="mt-3 flex flex-wrap gap-3">
            <button type="button" onClick={assistant.startRecording} className="v3-btn v3-btnFill">
              Записать снова
            </button>
            <button type="button" onClick={onFocusInput} className="v3-btn">
              Написать текстом
            </button>
          </div>
        ) : null}
      </div>
    );
  }

  const reply = message.reply;
  const options = active ? quickReplies(reply) : [];
  const hint = active ? voiceHint(reply) : null;

  return (
    <div>
      <p className={cn("v3-say", latest ? "v3-sayLatest" : "v3-muted")}>
        <TypedText text={message.text} animate={fresh} />
      </p>

      {reply?.kind === "confirmation" && latest && assistant.undoSecondsLeft !== null ? (
        <UndoBar seconds={assistant.undoSecondsLeft} onUndo={assistant.undo} />
      ) : null}
      {reply?.kind === "list" ? <EventRows events={reply.events} /> : null}
      {reply?.kind === "search_results" ? (
        <>
          <EventRows events={reply.events} withDate />
          <p className="v3-muted mt-2 text-sm">Искал по смыслу, а не по точным словам.</p>
        </>
      ) : null}

      {reply?.kind === "choice" ? (
        <ol className="v3-inset mt-3 grid py-1">
          {reply.choices.map(({ index, event }) => (
            <li key={event.id}>
              {active ? (
                <button
                  type="button"
                  onClick={() => assistant.submitText(choiceText(index))}
                  className="v3-menuItem"
                >
                  <span>
                    <span className="v3-pixel mr-2 text-[1.25rem]">{index}.</span>
                    {event.title}
                    <span className="v3-muted block text-sm">{formatWhen(event)}</span>
                  </span>
                </button>
              ) : (
                <p className="v3-muted px-3 py-1">
                  {index}. {event.title}, {formatWhen(event)}
                </p>
              )}
            </li>
          ))}
        </ol>
      ) : null}

      {options.length > 0 ? (
        <ul className="v3-inset mt-3 grid py-1 sm:max-w-[22rem]">
          {options.map((option) => (
            <li key={option.text}>
              <button
                type="button"
                onClick={() => assistant.submitText(option.text)}
                className={cn(
                  "v3-menuItem v3-pixel text-[1.25rem]",
                  option.tone === "danger" && "v3-menuDanger",
                )}
              >
                <span>{option.label}</span>
              </button>
            </li>
          ))}
          {reply?.pending?.expects === "time" ? (
            <li>
              <button
                type="button"
                onClick={onFocusInput}
                className="v3-menuItem v3-pixel text-[1.25rem]"
              >
                <span>Другое время…</span>
              </button>
            </li>
          ) : null}
        </ul>
      ) : null}
      {hint ? <p className="v3-muted mt-2 text-sm">{hint}</p> : null}
    </div>
  );
}

/** История разговора в окне диалога: реплики человека справа, Горького — слева. */
export function BalloonDialog({
  assistant,
  onFocusInput,
}: {
  assistant: DemoAssistant;
  onFocusInput: () => void;
}) {
  const { messages, phase } = assistant;
  const lastAssistant = messages.findLastIndex((message) => message.role === "assistant");

  return (
    <div className="grid gap-5">
      {messages.map((message, index) => {
        if (message.role === "user") {
          return (
            <div key={message.id} className="flex justify-end">
              <div className="v3-userBubble max-w-[85%] px-3.5 py-2">
                <span className="sr-only">Вы:</span>
                <p>{message.text}</p>
                <p className="v3-muted mt-0.5 flex items-center justify-end gap-1.5 text-xs">
                  {message.via === "voice" ? <PixelGlyph name="mic" size={10} /> : null}
                  {formatTime(message.created_at)}
                  {message.via === "voice" ? ", голосом" : ""}
                </p>
              </div>
            </div>
          );
        }
        const latest = index === lastAssistant && phase.name !== "processing";
        return (
          <div key={message.id} className="max-w-[40rem]">
            <p className="v3-speaker">Горький</p>
            <GorkyLine
              message={message}
              latest={latest}
              active={latest && assistant.pending !== null}
              fresh={message.live === true}
              assistant={assistant}
              onFocusInput={onFocusInput}
            />
          </div>
        );
      })}
      {showSuggestions(phase, assistant.pending, messages.length) ? (
        <div>
          <p className="v3-speaker">Что спросить</p>
          <ul className="v3-inset mt-2 grid py-1">
            {EXAMPLE_PHRASES.map((phrase) => (
              <li key={phrase}>
                <button
                  type="button"
                  onClick={() => assistant.submitText(phrase)}
                  className="v3-menuItem"
                >
                  <span>{phrase}</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {phase.name === "processing" ? (
        <div>
          <p className="v3-speaker">Горький</p>
          <p className="v3-say v3-muted">
            {phase.stage === "recognizing" ? "Разбираю, что вы сказали" : "Думаю"}
            <span className="v3-dots" aria-hidden="true">
              <span>.</span>
              <span>.</span>
              <span>.</span>
            </span>
          </p>
        </div>
      ) : null}
    </div>
  );
}
