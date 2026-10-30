"use client";

import { tty } from "@/components/ui/tty";
import { cn } from "@/lib/cn";
import { formatTime } from "@/lib/format";

import type { Assistant } from "../hooks/use-assistant";
import type { NoticeAction, NoticeEntry } from "../model/conversation";
import { ReplyBlock } from "./reply-block";
import { Spinner } from "./spinner";

/** фразы из ТЗ: по одной на каждое ключевое действие. */
const EXAMPLE_PHRASES = [
  "Напомни мне завтра в 10 утра позвонить Ивану",
  "Добавь встречу с командой завтра в 15:00",
  "Что у меня сегодня?",
  "Найди задачу про презентацию",
];

const ACTION_LABELS: Record<NoticeAction["type"], string> = {
  record: "записать снова",
  type: "написать текстом",
  resend: "повторить",
  "reload-history": "загрузить снова",
};

function lowerFirst(text: string): string {
  return text.charAt(0).toLowerCase() + text.slice(1);
}

export type LogHandlers = {
  focusInput: () => void;
};

function Notice({
  notice,
  assistant,
  handlers,
  isLast,
}: {
  notice: NoticeEntry;
  assistant: Assistant;
  handlers: LogHandlers;
  isLast: boolean;
}) {
  const run = (action: NoticeAction) => {
    switch (action.type) {
      case "record":
        assistant.toggleRecording();
        return;
      case "type":
        handlers.focusInput();
        return;
      case "resend":
        assistant.sendText(action.text);
        return;
      case "reload-history":
        assistant.reloadHistory();
        return;
    }
  };

  if (notice.tone === "alarm") {
    return (
      <p className={cn(tty.alarm, "-ml-[1ch] py-0.5 pl-[1ch] text-pretty")}>
        <span className={tty.time}>{formatTime(notice.createdAt)} </span>
        <span className={cn(tty.accent, tty.strong)} aria-hidden="true">
          !{" "}
        </span>
        {notice.text}
      </p>
    );
  }

  return (
    <div className="pl-[3ch]">
      <p className={cn(tty.danger, "text-pretty")}>
        <span aria-hidden="true">✗ </span>
        {notice.text}
      </p>
      {isLast && notice.actions.length > 0 ? (
        <div className="mt-1 flex flex-wrap gap-x-3">
          {notice.actions.map((action) => (
            <button
              key={action.type}
              type="button"
              aria-disabled={assistant.sending || undefined}
              onClick={(event) => {
                if (assistant.sending) return;
                run(action);
                if (
                  event.detail === 0 &&
                  (action.type === "resend" || action.type === "reload-history")
                ) {
                  handlers.focusInput();
                }
              }}
              className={tty.btn}
            >
              {ACTION_LABELS[action.type]}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}

/** история диалога как лог терминальной сессии. */
export function SessionLog({
  assistant,
  now,
  handlers,
}: {
  assistant: Assistant;
  now: Date | null;
  handlers: LogHandlers;
}) {
  const { conversation } = assistant;
  const { entries, history, activity } = conversation;
  const hasDialog = entries.some((entry) => entry.kind !== "notice");
  const showSuggestions =
    history === "ready" && activity.name === "idle" && assistant.pending === null && !hasDialog;

  return (
    <div className="grid gap-4">
      <div className={cn(tty.muted, "text-xs text-pretty")}>
        <p>Горький — голосовой ассистент задач, напоминаний и встреч.</p>
        <p>
          Нажмите «говорить» или напишите в строке ниже. Ответы звучат вслух — выключить можно внизу
          экрана.
        </p>
      </div>

      {history === "loading" ? (
        <p className="flex items-center gap-[1ch] pl-[3ch]" aria-busy="true">
          <Spinner />
          <span className={tty.muted}>загружаю историю…</span>
        </p>
      ) : null}
      {history === "failed" ? (
        <div className="pl-[3ch]">
          <p className={tty.danger}>
            <span aria-hidden="true">✗ </span>
            История не загрузилась. Проверьте связь с сервером.
          </p>
          <button type="button" onClick={assistant.reloadHistory} className={cn(tty.btn, "mt-1")}>
            загрузить снова
          </button>
        </div>
      ) : null}
      {conversation.hasOlder ? (
        <div className="pl-[3ch]">
          <button
            type="button"
            aria-disabled={conversation.loadingOlder || undefined}
            onClick={() => {
              if (!conversation.loadingOlder) assistant.loadOlder();
            }}
            className={tty.btn}
          >
            {conversation.loadingOlder ? "загружаю…" : "показать более ранние"}
          </button>
        </div>
      ) : null}

      {entries.map((entry, index) => (
        <div key={entry.key} data-log-entry="" data-role={entry.kind}>
          {entry.kind === "notice" ? (
            <Notice
              notice={entry}
              assistant={assistant}
              handlers={handlers}
              isLast={index === entries.length - 1}
            />
          ) : entry.kind === "user" ? (
            <p className="flex flex-wrap items-baseline gap-x-[1ch]">
              <span className={tty.time}>{formatTime(entry.createdAt)}</span>
              <span className={tty.prompt} aria-hidden="true">
                $
              </span>
              <span className="sr-only">Вы:</span>
              <span className={cn(tty.strong, "min-w-0 flex-1 break-words")}>{entry.text}</span>
              {entry.via === "voice" ? (
                <span className={cn(tty.muted, "text-xs")}>голосом</span>
              ) : null}
              {entry.failed ? <span className={cn(tty.danger, "text-xs")}>без ответа</span> : null}
            </p>
          ) : (
            <>
              <span className="sr-only">Горький:</span>
              <ReplyBlock
                entry={entry}
                active={entry.key === assistant.activeKey}
                busy={assistant.sending}
                now={now}
                undoSeconds={assistant.undoSecondsLeft(entry.messageId)}
                actions={{
                  send: assistant.sendText,
                  undo: () => {
                    const actionId = entry.reply?.undo?.action_id;
                    if (actionId) assistant.undo(entry.messageId, actionId);
                  },
                  focusInput: handlers.focusInput,
                }}
              />
            </>
          )}
        </div>
      ))}

      {showSuggestions ? (
        <div className="pl-[3ch]">
          <p className={cn(tty.muted, "text-xs")}>попробуйте сказать или нажмите:</p>
          <ul className="mt-1 grid justify-items-start gap-0.5">
            {EXAMPLE_PHRASES.map((phrase) => (
              <li key={phrase}>
                <button
                  type="button"
                  onClick={(event) => {
                    assistant.sendText(phrase);
                    // кнопка исчезнет вместе с подсказками — с клавиатуры фокус в строку ввода.
                    if (event.detail === 0) handlers.focusInput();
                  }}
                  className={cn(tty.btn, tty.btnCmd)}
                >
                  {lowerFirst(phrase)}
                </button>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {activity.name === "sending" ? (
        <p className="flex items-center gap-[1ch] pl-[3ch]">
          <Spinner />
          <span className={tty.muted}>
            {activity.via === "voice" ? "распознаю речь и разбираю запрос…" : "разбираю запрос…"}
          </span>
        </p>
      ) : null}
    </div>
  );
}
