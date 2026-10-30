"use client";

import type { MouseEvent, ReactNode } from "react";

import { tty } from "@/components/ui/tty";
import { formatWhen } from "@/features/events/model/event-format";
import { cn } from "@/lib/cn";
import type { AssistantReply, Period } from "@/types/api";

import type { AssistantEntry } from "../model/conversation";
import { choiceText, quickReplies, voiceHint } from "../model/quick-replies";
import { EventsTable, type TableScale } from "./events-table";
import { UndoControl } from "./undo-control";

const DAY_MS = 86_400_000;

function listScale(period: Period | null): TableScale {
  if (!period) return "day";
  return Date.parse(period.to) - Date.parse(period.from) <= DAY_MS ? "time" : "day";
}

/** В консоли все команды-кнопки со строчной буквы, как в TUI. */
function lowerFirst(text: string): string {
  return text.charAt(0).toLowerCase() + text.slice(1);
}

function Question({ active, children }: { active: boolean; children: ReactNode }) {
  return (
    <p className={cn(active && tty.question, "-ml-[1ch] py-0.5 pl-[1ch]")}>
      <span className={cn(tty.wait, tty.strong)} aria-hidden="true">
        ?{" "}
      </span>
      {children}
    </p>
  );
}

export type ReplyActions = {
  /** отправить реплику от имени пользователя (быстрый ответ, выбор варианта). */
  send: (text: string) => void;
  undo: () => void;
  focusInput: () => void;
};

/** ответ ассистента в логе: вид зависит от `kind` (контракт AssistantReply). */
export function ReplyBlock({
  entry,
  active,
  busy,
  now,
  undoSeconds,
  actions,
}: {
  entry: AssistantEntry;
  /** на вопрос этой реплики ещё можно ответить кнопками. */
  active: boolean;
  /** идёт запрос — кнопки ответа недоступны, но остаются в фокусе. */
  busy: boolean;
  now: Date | null;
  undoSeconds: number | null;
  actions: ReplyActions;
}) {
  const reply: AssistantReply | null = entry.reply;
  if (!reply) return <p className="pl-[3ch]">{entry.text}</p>;

  const options = active ? quickReplies(reply) : [];
  const hint = active ? voiceHint(reply.pending) : null;
  // кнопка ответа исчезнет вместе с вопросом: с клавиатуры (detail = 0) фокус — в строку ввода.
  const sendIfIdle = (text: string, event: MouseEvent<HTMLButtonElement>) => {
    if (busy) return;
    actions.send(text);
    if (event.detail === 0) actions.focusInput();
  };

  const quickButtons =
    options.length > 0 || (active && reply.pending?.expects === "time") ? (
      <div className="mt-1.5 flex flex-wrap gap-x-2 gap-y-1">
        {options.map((option) => (
          <button
            key={option.label}
            type="button"
            aria-disabled={busy || undefined}
            onClick={(event) => sendIfIdle(option.text, event)}
            className={cn(tty.btn, option.tone === "danger" && tty.btnDanger)}
          >
            {lowerFirst(option.label)}
          </button>
        ))}
        {reply.pending?.expects === "time" ? (
          <button type="button" onClick={actions.focusInput} className={tty.btn}>
            другое время
          </button>
        ) : null}
      </div>
    ) : null;

  const hintLine = hint ? <p className={cn(tty.muted, "mt-1 text-xs")}>{hint}</p> : null;

  switch (reply.kind) {
    case "confirmation":
      return (
        <div className="pl-[3ch]">
          <p>
            <span className={cn(tty.ok, tty.strong)} aria-hidden="true">
              ✓{" "}
            </span>
            {reply.text}
          </p>
          {reply.undo && undoSeconds !== null ? (
            <UndoControl
              seconds={undoSeconds}
              onUndo={(event) => {
                actions.undo();
                if (event.detail === 0) actions.focusInput();
              }}
            />
          ) : null}
        </div>
      );
    case "list":
      return (
        <div className="pl-[3ch]">
          <p>{reply.text}</p>
          <EventsTable
            events={reply.events}
            scale={listScale(reply.period)}
            now={now}
            highlightNext
            caption={reply.period ? `Записи ${reply.period.label}` : "Записи за период"}
          />
        </div>
      );
    case "search_results":
      return (
        <div className="pl-[3ch]">
          <p>{reply.text}</p>
          <EventsTable events={reply.events} scale="date" now={now} caption="Найденные записи" />
          {reply.events.length > 0 ? (
            <p className={cn(tty.muted, "mt-1 text-xs")}>искал по смыслу, а не по точным словам</p>
          ) : null}
        </div>
      );
    case "clarification":
      return (
        <div className="pl-[3ch]">
          <Question active={active}>{reply.text}</Question>
          {quickButtons}
          {hintLine}
        </div>
      );
    case "confirm_request": {
      const shown = reply.conflicts.length > 0 ? reply.conflicts : reply.events;
      return (
        <div className="pl-[3ch]">
          <Question active={active}>{reply.text}</Question>
          <EventsTable
            events={shown}
            scale="day"
            now={now}
            caption={reply.conflicts.length > 0 ? "Пересекается с" : "Что будет удалено"}
          />
          {quickButtons}
          {hintLine}
        </div>
      );
    }
    case "choice":
      return (
        <div className="pl-[3ch]">
          <Question active={active}>{reply.text}</Question>
          <ol className="mt-1.5 grid gap-0.5">
            {reply.choices.map(({ index, event }) => {
              const when = now ? formatWhen(event, now) : "";
              return (
                <li key={`${index}-${event.id}`}>
                  {active ? (
                    <button
                      type="button"
                      aria-disabled={busy || undefined}
                      onClick={(event) => sendIfIdle(choiceText(index), event)}
                      className={cn(tty.btn, "w-full justify-start text-left whitespace-normal")}
                    >
                      <span className={tty.wide}>{index})</span>
                      <span className={tty.fg}>{event.title}</span>
                      <span className={cn(tty.muted, "font-normal")}>{when}</span>
                    </button>
                  ) : (
                    <span>
                      {index}) {event.title}
                      {when ? `, ${when}` : ""}
                    </span>
                  )}
                </li>
              );
            })}
          </ol>
          {hintLine}
        </div>
      );
    case "info":
      return <p className="pl-[3ch]">{reply.text}</p>;
  }
}
