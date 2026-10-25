"use client";

import { Fragment, useRef, useState } from "react";

import { MAIN_CONTENT_ID, SkipLink } from "@/components/skip-link";
import { cn } from "@/lib/cn";

import { DemoBar } from "../components/demo-bar";
import { SettingsMenu } from "../components/settings-menu";
import { ThemeChoice } from "../components/theme-choice";
import { useDemoAssistant } from "../hooks/use-demo-assistant";
import { useScrollToLatest } from "../hooks/use-scroll-to-latest";
import { ANSWER_SOUND_LABEL, sphereStatus } from "../model/copy";
import { DEMO_NOW, EVENT_TEAM_MEETING } from "../model/mock-data";
import {
  TYPE_LABELS,
  eventTiming,
  eventsOnDay,
  formatDayMonth,
  formatDuration,
  formatEventTime,
  formatIn,
  formatTime,
  formatWeekday,
  nextEvent,
  nowIndex,
} from "../model/format";
import type { CalendarEvent, DemoStateId } from "../model/types";
import { EngravedSphere } from "./engraved-sphere";
import { manuscriptSans, manuscriptSerif } from "./fonts";
import { ManuscriptDialog } from "./manuscript-dialog";
import "./manuscript.css";

const CAPTIONS: Record<string, string> = {
  idle: "Нажмите на шар и говорите",
  listening: "Слушаю",
  thinking: "Думаю",
  speaking: "Отвечаю вслух",
  waiting: "Жду вашего ответа",
  error: "Не расслышал",
};

function capitalize(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function TocEntry({ event }: { event: CalendarEvent }) {
  const timing = eventTiming(event);
  const muted = timing === "done" || timing === "past";
  const soon = timing === "later" && event.starts_at ? formatIn(event.starts_at) : null;
  return (
    <li className={cn(event.id === EVENT_TEAM_MEETING.id && "v2-fresh rounded-sm")}>
      <div className="v2-tocLine">
        <span
          className={cn(
            "v2-tocTitle min-w-0",
            muted && "v2-muted",
            timing === "done" && "v2-struck",
          )}
        >
          {event.title}
        </span>
        <span className="v2-leader" aria-hidden="true" />
        <span className={cn("v2-tocTime shrink-0", muted ? "v2-muted" : "v2-violet")}>
          {formatEventTime(event)}
        </span>
      </div>
      <p className="v2-tag">
        {TYPE_LABELS[event.type]}
        {timing === "done" ? ", сделано" : ""}
        {timing === "past" ? ", прошла" : ""}
        {soon && event.type !== "task" ? `, ${soon}` : ""}
        {event.type === "task" && timing === "later" ? ", до конца дня" : ""}
      </p>
    </li>
  );
}

/** Содержание дня: записи как главы, время — как номера страниц. */
function DayContents({ feed }: { feed: CalendarEvent[] }) {
  const today = eventsOnDay(feed, 0);
  const tomorrow = eventsOnDay(feed, 1);
  const now = nowIndex(today);
  const tomorrowDate = new Date(DEMO_NOW.getTime() + 86_400_000);

  return (
    <div className="grid gap-8">
      <section aria-labelledby="v2-today">
        <h2 id="v2-today" className="v2-sectionTitle">
          {capitalize(formatWeekday(DEMO_NOW))}, {formatDayMonth(DEMO_NOW)}
        </h2>
        <ul className="mt-4 grid gap-2.5">
          {today.map((event, index) => (
            <Fragment key={event.id}>
              {index === now ? (
                <li className="v2-now py-0.5">сейчас {formatTime(DEMO_NOW.toISOString())}</li>
              ) : null}
              <TocEntry event={event} />
            </Fragment>
          ))}
        </ul>
      </section>
      <section aria-labelledby="v2-tomorrow">
        <h2 id="v2-tomorrow" className="v2-sectionSub">
          Завтра, {formatDayMonth(tomorrowDate)}
        </h2>
        <ul className="mt-3 grid gap-3">
          {tomorrow.map((event) => (
            <TocEntry key={event.id} event={event} />
          ))}
        </ul>
      </section>
    </div>
  );
}

/** Вариант 2 «Рукопись»: разворот книги — содержание дня и гравюра слева, разговор справа. */
export function ManuscriptScreen({
  initialState,
  showBar,
}: {
  initialState: DemoStateId;
  showBar: boolean;
}) {
  const assistant = useDemoAssistant(initialState);
  const [draft, setDraft] = useState("");
  const [tocOpen, setTocOpen] = useState(false);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const dialogRef = useScrollToLatest<HTMLDivElement>(
    `${assistant.messages.length}-${assistant.phase.name}`,
  );
  const recording = assistant.phase.name === "recording";
  const busy = assistant.phase.name === "processing";
  const upcoming = nextEvent(assistant.feed);

  const focusInput = () => inputRef.current?.focus();

  return (
    <div
      className={cn(
        "v2-root flex h-dvh flex-col",
        manuscriptSerif.variable,
        manuscriptSans.variable,
      )}
    >
      {showBar ? <DemoBar variant={2} current={assistant.preset} onJump={assistant.jump} /> : null}
      <SkipLink />

      <header className="v2-runningHead flex shrink-0 items-center gap-4 px-4 py-3 sm:px-8 lg:py-4">
        <p className="v2-wordmark" translate="no">
          Горький
        </p>
        <h1 className="sr-only">Горький — голосовой ассистент задач и встреч</h1>
        <p className="v2-muted mx-auto text-sm max-sm:hidden">
          {capitalize(formatWeekday(DEMO_NOW))}, {formatDayMonth(DEMO_NOW)},{" "}
          {formatTime(DEMO_NOW.toISOString())}
        </p>
        <div className="flex items-center gap-2 max-sm:ml-auto">
          <label className="v2-toggle gap-2 max-lg:hidden">
            <input
              type="checkbox"
              checked={assistant.soundOn}
              onChange={(event) => assistant.setSoundOn(event.target.checked)}
              className="size-4 accent-(--fill)"
            />
            {ANSWER_SOUND_LABEL}
          </label>
          <ThemeChoice
            className="flex items-center max-lg:hidden"
            legendClassName="sr-only"
            optionClassName="v2-toggle"
          />
          <SettingsMenu
            soundOn={assistant.soundOn}
            onSoundChange={assistant.setSoundOn}
            trigger={
              <button type="button" className="v2-btn lg:hidden">
                Настройки
              </button>
            }
          />
        </div>
      </header>

      <main
        id={MAIN_CONTENT_ID}
        tabIndex={-1}
        className={cn(
          "v2-spread grid min-h-0 flex-1 outline-none",
          "grid-cols-[minmax(0,1fr)] grid-rows-[auto_minmax(0,1fr)_auto_auto]",
          "[grid-template-areas:'toc'_'dialog'_'sphere'_'composer']",
          "lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)] lg:grid-rows-[minmax(0,1fr)_auto_auto]",
          "lg:[grid-template-areas:'toc_dialog'_'sphere_dialog'_'sphere_composer']",
        )}
      >
        {/* Левая страница, верх: содержание дня. На телефоне — раскрывающаяся строка. */}
        <div className="min-h-0 [grid-area:toc] max-lg:border-b max-lg:border-(--rule) lg:overflow-y-auto lg:overscroll-contain lg:px-14 lg:pt-10 lg:pb-6">
          <button
            type="button"
            aria-expanded={tocOpen}
            aria-controls="v2-contents"
            onClick={() => setTocOpen((value) => !value)}
            className="flex min-h-12 w-full items-center gap-3 px-4 text-left lg:hidden"
          >
            <span className="v2-serif font-semibold">Сегодня</span>
            {upcoming?.starts_at ? (
              <span className="v2-muted min-w-0 truncate text-sm">
                дальше {formatTime(upcoming.starts_at)} {upcoming.title}
              </span>
            ) : null}
            <span className="v2-violet ml-auto text-sm font-semibold">
              {tocOpen ? "Свернуть" : "Открыть"}
            </span>
          </button>
          <div
            id="v2-contents"
            className={cn(
              "max-lg:max-h-[50dvh] max-lg:overflow-y-auto max-lg:px-4 max-lg:pb-5",
              !tocOpen && "max-lg:hidden",
            )}
          >
            <DayContents feed={assistant.feed} />
          </div>
        </div>

        {/* Правая страница: разговор. */}
        <div
          ref={dialogRef}
          role="log"
          aria-label="Разговор с Горьким"
          className="min-h-0 overflow-y-auto overscroll-contain px-4 pt-6 pb-6 [grid-area:dialog] sm:px-8 lg:px-16 lg:pt-10"
        >
          <div className="mx-auto max-w-[40rem]">
            <ManuscriptDialog assistant={assistant} onFocusInput={focusInput} />
          </div>
        </div>

        {/* Левая страница, низ: гравюра-сфера — она же кнопка записи. */}
        <div className="flex items-center gap-4 px-4 pt-3 [grid-area:sphere] max-lg:border-t max-lg:border-(--rule) lg:flex-col lg:justify-end lg:gap-3 lg:px-14 lg:pt-4 lg:pb-8">
          <button
            type="button"
            onClick={() => {
              if (busy) return;
              if (recording) assistant.stopRecording();
              else assistant.startRecording();
            }}
            aria-disabled={busy || undefined}
            aria-label={recording ? "Остановить запись" : "Говорить"}
            aria-describedby="v2-sphere-caption"
            className="v2-sphere size-20 shrink-0 aria-disabled:cursor-progress sm:size-24 lg:size-52"
          >
            <EngravedSphere
              mode={assistant.sphere}
              levelRef={assistant.levelRef}
              className="block size-full"
            />
          </button>
          <div className="grid min-w-0 gap-1 lg:justify-items-center lg:text-center">
            <p
              id="v2-sphere-caption"
              className={cn("v2-caption", assistant.sphere === "error" ? "v2-danger" : "v2-violet")}
            >
              {CAPTIONS[assistant.sphere]}
              {recording ? `, ${formatDuration(assistant.recordingSeconds)}` : ""}
            </p>
            <p role="status" className="sr-only">
              {sphereStatus(assistant.sphere, assistant.phase)}
            </p>
            {recording ? (
              <p className="flex flex-wrap items-center gap-x-3 lg:justify-center">
                <span className="v2-tag">остановлюсь сам после паузы</span>
                <button type="button" onClick={assistant.cancelRecording} className="v2-linkBtn">
                  Отменить, Esc
                </button>
              </p>
            ) : (
              <p className="v2-tag max-sm:hidden">
                {assistant.sphere === "waiting"
                  ? "Можно ответить голосом, текстом или кнопкой"
                  : "Или напишите — справа, в строке ниже"}
              </p>
            )}
          </div>
        </div>

        {/* Правая страница, низ: строка ввода. */}
        <form
          aria-label="Сообщение для Горького"
          className="px-4 pt-2 pb-4 [grid-area:composer] sm:px-8 lg:px-16 lg:pb-8"
          onSubmit={(event) => {
            event.preventDefault();
            if (busy) return;
            assistant.submitText(draft);
            setDraft("");
          }}
        >
          <div className="v2-field mx-auto flex max-w-[40rem] items-center gap-3">
            <label htmlFor="v2-input" className="sr-only">
              Сообщение для Горького
            </label>
            <input
              ref={inputRef}
              id="v2-input"
              name="text"
              type="text"
              autoComplete="off"
              enterKeyHint="send"
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              placeholder={
                assistant.pending?.expects === "time" ? "Например, в 16:30" : "Что у меня завтра?"
              }
              className="v2-input h-12"
            />
            <button
              type="submit"
              aria-busy={busy || undefined}
              className="v2-btn v2-btnFill shrink-0 max-sm:px-4"
            >
              Отправить
            </button>
          </div>
        </form>
      </main>
    </div>
  );
}
