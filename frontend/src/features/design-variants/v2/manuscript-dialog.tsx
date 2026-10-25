"use client";

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

/** Пиксельная «каретка» перед репликой человека — терминальная деталь в книжном развороте. */
function PixelCaret() {
  return (
    <svg
      width="8"
      height="10"
      viewBox="0 0 4 5"
      aria-hidden="true"
      shapeRendering="crispEdges"
      className="v2-pixel shrink-0 translate-y-[-1px]"
    >
      <rect x="0" y="0" width="1" height="1" fill="currentColor" />
      <rect x="1" y="1" width="1" height="1" fill="currentColor" />
      <rect x="2" y="2" width="1" height="1" fill="currentColor" />
      <rect x="1" y="3" width="1" height="1" fill="currentColor" />
      <rect x="0" y="4" width="1" height="1" fill="currentColor" />
    </svg>
  );
}

function TocList({ events }: { events: CalendarEvent[] }) {
  return (
    <ul className="mt-3 grid max-w-[38rem] gap-2.5">
      {events.map((event) => {
        const done = eventTiming(event) === "done";
        return (
          <li key={event.id}>
            <div className="v2-tocLine">
              <span className={cn("v2-tocTitle v2-violet min-w-0", done && "v2-struck")}>
                {event.title}
              </span>
              <span className="v2-leader" aria-hidden="true" />
              <span className="v2-tocTime v2-violet shrink-0">{formatEventTime(event)}</span>
            </div>
            <p className="v2-tag">
              {TYPE_LABELS[event.type]}
              {done ? ", сделано" : ""}
            </p>
          </li>
        );
      })}
    </ul>
  );
}

function Citations({ events }: { events: CalendarEvent[] }) {
  return (
    <ol className="mt-3 grid max-w-[38rem] gap-3">
      {events.map((event) => (
        <li key={event.id} className="border-l-2 border-(--rule) pl-4">
          <p>
            <span className="v2-serif text-[1.0625rem] text-(--ink)">{event.title}.</span>{" "}
            <span className="v2-muted text-[0.9375rem]">
              {event.starts_at ? formatDayLabel(event.starts_at) : "без срока"},{" "}
              {TYPE_LABELS[event.type]}, {event.status === "done" ? "выполнено" : "открыто"}
            </span>
          </p>
        </li>
      ))}
    </ol>
  );
}

function Reply({
  message,
  latest,
  active,
  assistant,
  onOtherTime,
}: {
  message: DemoMessage;
  latest: boolean;
  active: boolean;
  assistant: DemoAssistant;
  onOtherTime: () => void;
}) {
  const textClass = cn("v2-reply", latest && "v2-replyLatest");

  if (message.failure) {
    return (
      <div>
        <p className={cn(textClass, "text-(--danger) italic")}>{message.text}</p>
        {latest ? (
          <div className="mt-4 flex flex-wrap items-center gap-x-5 gap-y-2">
            <button type="button" onClick={assistant.startRecording} className="v2-btn v2-btnFill">
              Записать снова
            </button>
            <button type="button" onClick={onOtherTime} className="v2-linkBtn">
              Написать текстом
            </button>
          </div>
        ) : null}
      </div>
    );
  }

  const reply = message.reply;
  if (!reply) return <p className={textClass}>{message.text}</p>;
  const options = active ? quickReplies(reply) : [];
  const hint = active ? voiceHint(reply) : null;

  return (
    <div>
      <p className={textClass}>{reply.text}</p>

      {reply.kind === "confirmation" && latest && assistant.undoSecondsLeft !== null ? (
        <div className="mt-3 inline-grid gap-1">
          <div className="flex items-baseline gap-3">
            <button type="button" onClick={assistant.undo} className="v2-linkBtn">
              Отменить
            </button>
            <span className="v2-tag">ещё {assistant.undoSecondsLeft} с</span>
          </div>
          <span
            className="v2-undoLine"
            style={{ scale: `${assistant.undoSecondsLeft / 10} 1` }}
            aria-hidden="true"
          />
        </div>
      ) : null}

      {reply.kind === "list" ? <TocList events={reply.events} /> : null}
      {reply.kind === "search_results" ? (
        <>
          <Citations events={reply.events} />
          <p className="v2-tag mt-2">Искал по смыслу, не по точным словам.</p>
        </>
      ) : null}

      {reply.kind === "choice" ? (
        <ol className="mt-3 grid max-w-[38rem] gap-1">
          {reply.choices.map(({ index, event }) => (
            <li key={event.id}>
              {active ? (
                <button
                  type="button"
                  onClick={() => assistant.submitText(choiceText(index))}
                  className="v2-choice"
                >
                  <span className="v2-choiceNum">{index}</span>
                  <span>
                    <span className="v2-serif block text-[1.0625rem]">{event.title}</span>
                    <span className="v2-muted block text-[0.9375rem]">{formatWhen(event)}</span>
                  </span>
                </button>
              ) : (
                <p className="v2-muted">
                  {index}. {event.title}, {formatWhen(event)}
                </p>
              )}
            </li>
          ))}
        </ol>
      ) : null}

      {options.length > 0 ? (
        <div className="mt-4 flex flex-wrap gap-2">
          {options.map((option) => (
            <button
              key={option.text}
              type="button"
              onClick={() => assistant.submitText(option.text)}
              className={cn("v2-btn", option.tone === "danger" && "v2-btnDanger")}
            >
              {option.label}
            </button>
          ))}
          {reply.pending?.expects === "time" ? (
            <button type="button" onClick={onOtherTime} className="v2-linkBtn px-2">
              Другое время
            </button>
          ) : null}
        </div>
      ) : null}
      {hint ? <p className="v2-tag mt-2">{hint}</p> : null}
    </div>
  );
}

/** Разговор: реплика человека — строкой гротеска, ответ Горького — абзацем антиквы. */
export function ManuscriptDialog({
  assistant,
  onFocusInput,
}: {
  assistant: DemoAssistant;
  onFocusInput: () => void;
}) {
  const { messages, phase } = assistant;
  const lastAssistant = messages.findLastIndex((message) => message.role === "assistant");

  return (
    <div className="grid gap-7">
      {messages.map((message, index) => {
        if (message.role === "user") {
          return (
            <div key={message.id} className="v2-userLine flex items-baseline gap-2.5">
              <PixelCaret />
              <span className="sr-only">Вы:</span>
              <p className="min-w-0">
                {message.text}
                <span className="v2-tag ml-2 whitespace-nowrap">
                  {formatTime(message.created_at)}
                  {message.via === "voice" ? ", голосом" : ""}
                </span>
              </p>
            </div>
          );
        }
        const latest = index === lastAssistant && phase.name !== "processing";
        return (
          <div key={message.id} className="-mt-3">
            <span className="sr-only">Горький:</span>
            <Reply
              message={message}
              latest={latest}
              active={latest && assistant.pending !== null}
              assistant={assistant}
              onOtherTime={onFocusInput}
            />
          </div>
        );
      })}
      {showSuggestions(phase, assistant.pending, messages.length) ? (
        <div>
          <p className="v2-tag">Скажите или нажмите, например:</p>
          <ul className="mt-3 flex flex-wrap gap-2">
            {EXAMPLE_PHRASES.map((phrase) => (
              <li key={phrase}>
                <button
                  type="button"
                  onClick={() => assistant.submitText(phrase)}
                  className="v2-btn v2-serif font-normal italic"
                >
                  «{phrase}»
                </button>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {phase.name === "processing" ? (
        <p className="v2-caption v2-violet -mt-3">
          {phase.stage === "recognizing" ? "Разбираю, что вы сказали" : "Пишу ответ"}
          <span className="v2-dots" aria-hidden="true">
            <span>.</span>
            <span>.</span>
            <span>.</span>
          </span>
        </p>
      ) : null}
    </div>
  );
}
