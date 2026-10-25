"use client";

import { type RefObject, useRef, useState } from "react";

import { MAIN_CONTENT_ID, SkipLink } from "@/components/skip-link";
import { cn } from "@/lib/cn";

import { DemoBar } from "../components/demo-bar";
import { SettingsMenu } from "../components/settings-menu";
import { ThemeChoice } from "../components/theme-choice";
import { useDemoAssistant } from "../hooks/use-demo-assistant";
import { useLevelMeter } from "../hooks/use-level-meter";
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
} from "../model/format";
import type { CalendarEvent, DemoStateId } from "../model/types";
import { BalloonDialog } from "./balloon-dialog";
import { balloonPixel, balloonSans } from "./fonts";
import { PixelBalloon } from "./pixel-balloon";
import { PixelCloud, PixelGlyph, eventGlyph } from "./pixel-glyphs";
import "./balloon.css";

const TAGS: Record<string, string> = {
  idle: "Готов слушать",
  listening: "Слушаю",
  thinking: "Думаю",
  speaking: "Отвечаю",
  waiting: "Жду ответа",
  error: "Не расслышал",
};

const RULER_FROM = 8;
const RULER_TO = 24;
const METER_SEGMENTS = 12;

function rulerPosition(iso: string): number {
  const date = new Date(iso);
  const hours = Number(
    new Intl.DateTimeFormat("ru-RU", { hour: "numeric", timeZone: "Europe/Moscow" }).format(date),
  );
  const minutes = date.getUTCMinutes();
  return ((hours + minutes / 60 - RULER_FROM) / (RULER_TO - RULER_FROM)) * 100;
}

const STARS = [
  [6, 10],
  [14, 26],
  [22, 6],
  [38, 18],
  [47, 9],
  [58, 30],
  [72, 12],
  [84, 24],
  [91, 7],
  [30, 38],
] as const;

/** Линейка дня у горизонта: часы, отметки записей и «сейчас». Только для глаз — список ниже. */
function HorizonRuler({ events }: { events: CalendarEvent[] }) {
  const hours = Array.from({ length: RULER_TO - RULER_FROM + 1 }, (_, i) => RULER_FROM + i);
  const now = rulerPosition(DEMO_NOW.toISOString());
  return (
    <div className="relative mt-6 h-16 select-none" aria-hidden="true">
      {events.map((event) =>
        event.starts_at ? (
          <span
            key={event.id}
            className={cn(
              "absolute bottom-4 -translate-x-1/2",
              event.type === "meeting" ? "v3-accent" : "v3-wait",
              eventTiming(event) === "done" && "opacity-50",
            )}
            style={{ left: `${rulerPosition(event.starts_at)}%` }}
          >
            <PixelGlyph name={eventGlyph(event)} size={14} />
          </span>
        ) : null,
      )}
      <span
        className="v3-accent absolute top-0 bottom-3 border-l-2 border-dashed border-current"
        style={{ left: `${now}%` }}
      />
      <span
        className="v3-accent absolute top-0 -translate-x-[calc(100%+6px)] text-xs font-bold tabular-nums"
        style={{ left: `${now}%` }}
      >
        {formatTime(DEMO_NOW.toISOString())}
      </span>
      <div className="v3-ruler absolute inset-x-0 bottom-3" />
      {hours.map((hour) => (
        <span
          key={hour}
          className="absolute bottom-0 flex -translate-x-1/2 flex-col items-center"
          style={{ left: `${((hour - RULER_FROM) / (RULER_TO - RULER_FROM)) * 100}%` }}
        >
          <span className={cn("w-[3px] bg-current", hour % 3 === 0 ? "h-3" : "h-1.5")} />
          {hour % 3 === 0 && hour < RULER_TO ? (
            <span className="absolute top-4 text-xs font-semibold tabular-nums">{hour}</span>
          ) : null}
        </span>
      ))}
    </div>
  );
}

function DayRow({ event }: { event: CalendarEvent }) {
  const timing = eventTiming(event);
  const muted = timing === "done" || timing === "past";
  const soon = timing === "later" && event.starts_at ? formatIn(event.starts_at) : null;
  return (
    <li
      className={cn(
        "v3-chipRow grid grid-cols-[3.75rem_auto_minmax(0,1fr)] items-baseline gap-x-2 px-3 py-2",
        event.id === EVENT_TEAM_MEETING.id && "v3-fresh",
      )}
    >
      <span className={cn("v3-pixel text-[1.25rem] leading-tight", muted && "v3-muted")}>
        {formatEventTime(event)}
      </span>
      <PixelGlyph
        name={eventGlyph(event)}
        size={12}
        className={cn(event.type === "meeting" ? "v3-accent" : "v3-wait", "self-center")}
      />
      <span className="min-w-0">
        <span className={cn(muted && "v3-muted", timing === "done" && "line-through")}>
          {event.title}
        </span>
        <span className="v3-muted block text-sm">
          {TYPE_LABELS[event.type]}
          {timing === "done" ? ", сделано" : ""}
          {timing === "past" ? ", прошла" : ""}
          {soon && event.type !== "task" ? `, ${soon}` : ""}
          {event.type === "task" && timing === "later" ? ", до конца дня" : ""}
        </span>
      </span>
    </li>
  );
}

function RecordingMeter({ levelRef, active }: { levelRef: RefObject<number>; active: boolean }) {
  const meterRef = useLevelMeter<HTMLSpanElement>(levelRef, active, (element, level) => {
    const lit = Math.round(Math.sqrt(level) * METER_SEGMENTS);
    element.querySelectorAll("span").forEach((segment, index) => {
      if (index < lit) segment.setAttribute("data-on", "");
      else segment.removeAttribute("data-on");
    });
  });
  return (
    <span ref={meterRef} className="flex h-5 items-end gap-1" aria-hidden="true">
      {Array.from({ length: METER_SEGMENTS }, (_, index) => (
        <span key={index} className="v3-seg h-full" />
      ))}
    </span>
  );
}

/** Вариант 3 «Шар»: пиксельное небо с шаром-сферой и окно диалога, как в RPG. */
export function BalloonScreen({
  initialState,
  showBar,
}: {
  initialState: DemoStateId;
  showBar: boolean;
}) {
  const assistant = useDemoAssistant(initialState);
  const [draft, setDraft] = useState("");
  const [dayOpen, setDayOpen] = useState(false);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const logRef = useScrollToLatest<HTMLDivElement>(
    `${assistant.messages.length}-${assistant.phase.name}`,
  );
  const recording = assistant.phase.name === "recording";
  const busy = assistant.phase.name === "processing";
  const today = eventsOnDay(assistant.feed, 0);
  const tomorrow = eventsOnDay(assistant.feed, 1);
  const upcoming = nextEvent(assistant.feed);
  const tone =
    assistant.sphere === "error" ? "error" : assistant.sphere === "waiting" ? "waiting" : undefined;

  const focusInput = () => inputRef.current?.focus();

  return (
    <div
      className={cn(
        "v3-root v3-sky relative flex h-dvh flex-col overflow-hidden",
        balloonPixel.variable,
        balloonSans.variable,
      )}
    >
      {showBar ? <DemoBar variant={3} current={assistant.preset} onJump={assistant.jump} /> : null}
      <SkipLink />

      {/* Звёзды (ночью) и облака — неподвижные, без анимации. */}
      <div className="pointer-events-none absolute inset-0" aria-hidden="true">
        {STARS.map(([x, y]) => (
          <span
            key={`${x}-${y}`}
            className="v3-star absolute size-1 bg-current"
            style={{ left: `${x}%`, top: `${y}%` }}
          />
        ))}
        <PixelCloud className="absolute top-[14%] left-[4%] max-lg:hidden" scale={7} />
        <PixelCloud
          className="absolute top-[30%] left-[40%] max-lg:top-[9%] max-lg:left-[62%]"
          scale={5}
        />
        <PixelCloud className="absolute top-[8%] left-[60%] max-lg:hidden" scale={4} />
      </div>

      <header className="relative flex shrink-0 items-center gap-3 px-4 py-3 sm:px-8 lg:py-5">
        <p className="v3-pixel text-[1.875rem] leading-none sm:text-[2.5rem]" translate="no">
          Горький
        </p>
        <h1 className="sr-only">Горький — голосовой ассистент задач и встреч</h1>
        <div className="ml-auto flex items-center gap-3">
          <label className="v3-toggle gap-2 max-lg:hidden">
            <input
              type="checkbox"
              checked={assistant.soundOn}
              onChange={(event) => assistant.setSoundOn(event.target.checked)}
              className="size-4 accent-(--fill)"
            />
            {ANSWER_SOUND_LABEL}
          </label>
          <ThemeChoice
            className="v3-inset flex items-center max-lg:hidden"
            legendClassName="sr-only"
            optionClassName="v3-toggle"
          />
          <SettingsMenu
            soundOn={assistant.soundOn}
            onSoundChange={assistant.setSoundOn}
            trigger={
              <button type="button" className="v3-btn lg:hidden">
                Настройки
              </button>
            }
          />
        </div>
      </header>

      <main
        id={MAIN_CONTENT_ID}
        tabIndex={-1}
        className="relative grid min-h-0 flex-1 grid-cols-[minmax(0,1fr)] grid-rows-[auto_minmax(0,1fr)] gap-6 px-4 pb-4 outline-none sm:px-8 lg:grid-cols-[minmax(0,1fr)_minmax(0,36rem)] lg:grid-rows-[minmax(0,1fr)] lg:gap-12 lg:pb-8"
      >
        {/* Небо: шар-сфера и день у горизонта. */}
        <section aria-labelledby="v3-day-title" className="flex min-h-0 flex-col">
          <div className="flex shrink-0 items-center justify-center gap-4 lg:min-h-[23rem] lg:flex-1 lg:flex-col lg:gap-5 lg:pb-8">
            <div className="relative">
              <PixelBalloon
                mode={assistant.sphere}
                levelRef={assistant.levelRef}
                className="h-[160px] w-[128px] lg:h-[320px] lg:w-[256px]"
              />
            </div>
            <div className="grid justify-items-start gap-2 lg:justify-items-center">
              <p className="v3-tag px-3 py-1" data-tone={tone}>
                {TAGS[assistant.sphere]}
                {recording ? ` ${formatDuration(assistant.recordingSeconds)}` : ""}
              </p>
              <p role="status" className="sr-only">
                {sphereStatus(assistant.sphere, assistant.phase)}
              </p>
              {upcoming?.starts_at ? (
                <p className="text-sm lg:hidden">
                  <span className="v3-muted">Дальше: </span>
                  {formatTime(upcoming.starts_at)} {upcoming.title}
                </p>
              ) : null}
            </div>
          </div>

          <div className="lg:mt-auto lg:min-h-0 lg:overflow-y-auto lg:overscroll-contain lg:pr-2">
            <div className="flex items-baseline gap-3">
              <h2 id="v3-day-title" className="v3-pixel text-[1.25rem]">
                Сегодня<span className="max-sm:hidden">, {formatWeekday(DEMO_NOW)}</span>,{" "}
                {formatDayMonth(DEMO_NOW)}
              </h2>
              <button
                type="button"
                aria-expanded={dayOpen}
                aria-controls="v3-day-list"
                onClick={() => setDayOpen((value) => !value)}
                className="v3-btn ml-auto min-h-9 px-3 text-sm lg:hidden"
              >
                {dayOpen ? "Свернуть" : "Весь день"}
              </button>
            </div>
            <div className="max-lg:hidden">
              <HorizonRuler events={today} />
            </div>
            <div id="v3-day-list" className={cn("mt-6 max-lg:mt-3", !dayOpen && "max-lg:hidden")}>
              <ul className="grid gap-1.5 sm:grid-cols-2">
                {today.map((event) => (
                  <DayRow key={event.id} event={event} />
                ))}
              </ul>
              {tomorrow.length > 0 ? (
                <>
                  <h3 className="v3-pixel mt-4 mb-2 text-[1.25rem]">Завтра</h3>
                  <ul className="grid gap-1.5 sm:grid-cols-2">
                    {tomorrow.map((event) => (
                      <DayRow key={event.id} event={event} />
                    ))}
                  </ul>
                </>
              ) : null}
            </div>
          </div>
        </section>

        {/* Окно диалога. */}
        <section
          aria-labelledby="v3-dialog-title"
          className="v3-box mt-5 flex min-h-0 flex-col lg:mt-6"
        >
          <h2 id="v3-dialog-title" className="v3-boxTitle">
            Разговор
          </h2>
          <div
            ref={logRef}
            role="log"
            aria-label="История разговора"
            className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-5 pt-7 pb-5 sm:px-7"
          >
            <BalloonDialog assistant={assistant} onFocusInput={focusInput} />
          </div>
          <form
            aria-label="Сообщение для Горького"
            className="flex items-center gap-3 border-t-[3px] border-(--box-inner) px-4 py-3 sm:px-5"
            onSubmit={(event) => {
              event.preventDefault();
              if (busy) return;
              assistant.submitText(draft);
              setDraft("");
            }}
          >
            {recording ? (
              <div className="flex min-w-0 flex-1 flex-wrap items-center gap-x-3 gap-y-2">
                <RecordingMeter levelRef={assistant.levelRef} active={recording} />
                <button type="button" onClick={assistant.cancelRecording} className="v3-btn">
                  Отмена, Esc
                </button>
              </div>
            ) : null}
            <div
              className={cn(
                "v3-inset v3-field flex min-w-0 flex-1 items-center px-3",
                recording && "hidden",
              )}
            >
              <label htmlFor="v3-input" className="sr-only">
                Сообщение для Горького
              </label>
              <span className="v3-pixel v3-accent mr-2" aria-hidden="true">
                ▶
              </span>
              <input
                ref={inputRef}
                id="v3-input"
                name="text"
                type="text"
                autoComplete="off"
                enterKeyHint="send"
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                placeholder={
                  assistant.pending?.expects === "time" ? "Например, в 16:30" : "Что у меня завтра?"
                }
                className="v3-input h-11"
              />
            </div>
            <button
              type="submit"
              aria-busy={busy || undefined}
              className={cn(
                "v3-btn",
                (recording || !draft) && "max-sm:hidden",
                recording && "hidden",
              )}
            >
              Отправить
            </button>
            <button
              type="button"
              data-recording={recording || undefined}
              aria-label={recording ? "Остановить запись" : "Говорить"}
              onClick={() => {
                if (busy) return;
                if (recording) assistant.stopRecording();
                else assistant.startRecording();
              }}
              aria-disabled={busy || undefined}
              className={cn(
                "v3-mic aria-disabled:cursor-progress aria-disabled:opacity-60",
                draft && !recording && "max-sm:hidden",
              )}
            >
              <span className="v3-micFace">
                <PixelGlyph name={recording ? "stop" : "mic"} size={28} />
              </span>
            </button>
          </form>
        </section>
      </main>
    </div>
  );
}
