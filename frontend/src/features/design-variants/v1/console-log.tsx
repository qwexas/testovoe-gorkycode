"use client";

import { useEffect, useState } from "react";

import { cn } from "@/lib/cn";

import type { DemoAssistant } from "../hooks/use-demo-assistant";
import { choiceText, quickReplies, showSuggestions, voiceHint } from "../model/copy";
import { EXAMPLE_PHRASES } from "../model/mock-data";
import {
  TYPE_LABELS,
  eventTiming,
  formatEventTime,
  formatIn,
  formatNumericDate,
  formatTime,
  formatWhen,
} from "../model/format";
import type { CalendarEvent, DemoMessage } from "../model/types";
import { styles } from "./styles";

const SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏";

/** В консоли все команды-кнопки со строчной буквы, как в TUI. */
function lowerFirst(text: string): string {
  return text.charAt(0).toLowerCase() + text.slice(1);
}
const UNDO_CELLS = 10;

function Spinner() {
  const [frame, setFrame] = useState(0);
  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return undefined;
    const interval = window.setInterval(() => setFrame((value) => value + 1), 80);
    return () => window.clearInterval(interval);
  }, []);
  return (
    <span aria-hidden="true" className={styles.accent}>
      {SPINNER[frame % SPINNER.length]}
    </span>
  );
}

function statusCell(event: CalendarEvent): { text: string; className?: string } {
  const timing = eventTiming(event);
  if (timing === "done") return { text: "сделано", className: styles.ok };
  if (timing === "past") return { text: "прошло", className: styles.muted };
  if (timing === "now") return { text: "идёт", className: styles.accent };
  if (!event.starts_at) return { text: "без срока" };
  return { text: formatIn(event.starts_at) ?? "", className: styles.muted };
}

/** Вывод «команды» — таблица событий за период. */
function EventsTable({ events, withDate }: { events: CalendarEvent[]; withDate?: boolean }) {
  const nextId = events.find((event) => eventTiming(event) === "later")?.id;
  return (
    <div className="mt-2 overflow-x-auto">
      <table className={cn(styles.table, "w-full max-w-[44rem]")}>
        <thead>
          <tr>
            <th scope="col">{withDate ? "дата" : "время"}</th>
            <th scope="col" className="max-sm:hidden">
              тип
            </th>
            <th scope="col">что</th>
            <th scope="col" className="max-sm:hidden">
              {withDate ? "статус" : "когда"}
            </th>
          </tr>
        </thead>
        <tbody>
          {events.map((event) => {
            const status = withDate
              ? { text: event.status === "done" ? "выполнено" : "открыто", className: styles.ok }
              : statusCell(event);
            return (
              <tr
                key={event.id}
                className={cn(
                  event.status === "done" && !withDate && styles.rowDone,
                  event.id === nextId && !withDate && styles.rowNext,
                )}
              >
                <td className="whitespace-nowrap">
                  {withDate && event.starts_at
                    ? formatNumericDate(event.starts_at)
                    : formatEventTime(event)}
                </td>
                <td className="whitespace-nowrap max-sm:hidden">{TYPE_LABELS[event.type]}</td>
                <td>
                  <span className={cn(event.status === "done" && !withDate && styles.struck)}>
                    {event.title}
                  </span>
                  <span className="block text-xs sm:hidden">
                    {TYPE_LABELS[event.type]}
                    {status.text ? `, ${status.text}` : ""}
                  </span>
                </td>
                <td className={cn("whitespace-nowrap max-sm:hidden", status.className)}>
                  {status.text}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function UndoControl({ seconds, onUndo }: { seconds: number; onUndo: () => void }) {
  const filled = Math.max(0, Math.min(UNDO_CELLS, seconds));
  return (
    <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1">
      <button type="button" onClick={onUndo} className={styles.btn}>
        отменить
      </button>
      <span className={styles.undoBar} aria-hidden="true">
        {"█".repeat(filled)}
        <span className={styles.muted}>{"░".repeat(UNDO_CELLS - filled)}</span>
      </span>
      <span className={cn(styles.muted, "text-xs")}>ещё {seconds} с</span>
    </div>
  );
}

function AssistantBlock({
  message,
  isLast,
  assistant,
  onOtherTime,
}: {
  message: DemoMessage;
  isLast: boolean;
  assistant: DemoAssistant;
  onOtherTime: () => void;
}) {
  if (message.failure) {
    return (
      <div className="pl-[3ch]">
        <p className={styles.danger}>
          <span aria-hidden="true">✗ </span>
          {message.text}
        </p>
        {isLast ? (
          <div className="mt-1 flex flex-wrap gap-x-3">
            <button type="button" onClick={assistant.startRecording} className={styles.btn}>
              записать снова
            </button>
            <button type="button" onClick={onOtherTime} className={styles.btn}>
              написать текстом
            </button>
          </div>
        ) : null}
      </div>
    );
  }

  const reply = message.reply;
  if (!reply) return <p className="pl-[3ch]">{message.text}</p>;
  const active = isLast && assistant.pending !== null;
  const options = active ? quickReplies(reply) : [];
  const hint = active ? voiceHint(reply) : null;

  switch (reply.kind) {
    case "confirmation":
      return (
        <div className="pl-[3ch]">
          <p>
            <span className={cn(styles.ok, styles.strong)} aria-hidden="true">
              ✓{" "}
            </span>
            {reply.text}
          </p>
          {isLast && assistant.undoSecondsLeft !== null ? (
            <UndoControl seconds={assistant.undoSecondsLeft} onUndo={assistant.undo} />
          ) : null}
        </div>
      );
    case "list":
      return (
        <div className="pl-[3ch]">
          <p>{reply.text}</p>
          <EventsTable events={reply.events} />
        </div>
      );
    case "search_results":
      return (
        <div className="pl-[3ch]">
          <p>{reply.text}</p>
          <EventsTable events={reply.events} withDate />
          <p className={cn(styles.muted, "mt-1 text-xs")}>искал по смыслу, а не по точным словам</p>
        </div>
      );
    case "clarification":
    case "confirm_request":
      return (
        <div className="pl-[3ch]">
          <p className={cn(active && styles.question, "-ml-[1ch] py-0.5 pl-[1ch]")}>
            <span className={cn(styles.wait, styles.strong)} aria-hidden="true">
              ?{" "}
            </span>
            {reply.text}
          </p>
          {options.length > 0 ? (
            <div className="mt-1.5 flex flex-wrap gap-x-2 gap-y-1">
              {options.map((option) => (
                <button
                  key={option.text}
                  type="button"
                  onClick={() => assistant.submitText(option.text)}
                  className={cn(styles.btn, option.tone === "danger" && styles.btnDanger)}
                >
                  {lowerFirst(option.label)}
                </button>
              ))}
              {reply.pending?.expects === "time" ? (
                <button type="button" onClick={onOtherTime} className={styles.btn}>
                  другое время
                </button>
              ) : null}
            </div>
          ) : null}
          {hint ? <p className={cn(styles.muted, "mt-1 text-xs")}>{hint}</p> : null}
        </div>
      );
    case "choice":
      return (
        <div className="pl-[3ch]">
          <p className={cn(active && styles.question, "-ml-[1ch] py-0.5 pl-[1ch]")}>
            <span className={cn(styles.wait, styles.strong)} aria-hidden="true">
              ?{" "}
            </span>
            {reply.text}
          </p>
          <ol className="mt-1.5 grid gap-0.5">
            {reply.choices.map(({ index, event }) => (
              <li key={event.id}>
                {active ? (
                  <button
                    type="button"
                    onClick={() => assistant.submitText(choiceText(index))}
                    className={cn(styles.btn, "w-full justify-start text-left whitespace-normal")}
                  >
                    <span className={styles.wide}>{index})</span>
                    <span className="text-(--fg)">{event.title}</span>
                    <span className={cn(styles.muted, "font-normal")}>{formatWhen(event)}</span>
                  </button>
                ) : (
                  <span>
                    {index}) {event.title}, {formatWhen(event)}
                  </span>
                )}
              </li>
            ))}
          </ol>
          {hint ? <p className={cn(styles.muted, "mt-1 text-xs")}>{hint}</p> : null}
        </div>
      );
    case "info":
      return <p className="pl-[3ch]">{reply.text}</p>;
  }
}

/** История диалога как лог терминальной сессии. */
export function ConsoleLog({
  assistant,
  onFocusInput,
}: {
  assistant: DemoAssistant;
  onFocusInput: () => void;
}) {
  const { messages, phase } = assistant;
  return (
    <div className="grid gap-4">
      <div className={cn(styles.muted, "text-xs")}>
        <p>Горький — голосовой ассистент задач, напоминаний и встреч.</p>
        <p>Нажмите «говорить» или напишите в строке ниже. История — с начала дня.</p>
      </div>
      {messages.map((message, index) => {
        const isLast = index === messages.length - 1;
        if (message.role === "user") {
          return (
            <div key={message.id} className="flex flex-wrap items-baseline gap-x-[1ch]">
              <span className={styles.time}>{formatTime(message.created_at)}</span>
              <span className={styles.prompt} aria-hidden="true">
                $
              </span>
              <span className="sr-only">Вы:</span>
              <span className={cn(styles.strong, "min-w-0 flex-1")}>{message.text}</span>
              {message.via === "voice" ? (
                <span className={cn(styles.muted, "text-xs")}>голосом</span>
              ) : null}
            </div>
          );
        }
        return (
          <div key={message.id}>
            <span className="sr-only">Горький:</span>
            <AssistantBlock
              message={message}
              isLast={isLast}
              assistant={assistant}
              onOtherTime={onFocusInput}
            />
          </div>
        );
      })}
      {showSuggestions(phase, assistant.pending, messages.length) ? (
        <div className="pl-[3ch]">
          <p className={cn(styles.muted, "text-xs")}>попробуйте сказать или нажмите:</p>
          <ul className="mt-1 grid justify-items-start gap-0.5">
            {EXAMPLE_PHRASES.map((phrase) => (
              <li key={phrase}>
                <button
                  type="button"
                  onClick={() => assistant.submitText(phrase)}
                  className={cn(styles.btn, styles.btnCmd)}
                >
                  {lowerFirst(phrase)}
                </button>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {phase.name === "processing" ? (
        <p className="flex items-center gap-[1ch] pl-[3ch]">
          <Spinner />
          <span className={styles.muted}>
            {phase.stage === "recognizing" ? "распознаю речь…" : "разбираю запрос…"}
          </span>
        </p>
      ) : null}
    </div>
  );
}
