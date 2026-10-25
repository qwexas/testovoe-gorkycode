"use client";

import { type KeyboardEvent, useRef, useState } from "react";

import { MAIN_CONTENT_ID, SkipLink } from "@/components/skip-link";
import { cn } from "@/lib/cn";

import { DemoBar } from "../components/demo-bar";
import { SettingsMenu } from "../components/settings-menu";
import { ThemeChoice } from "../components/theme-choice";
import { useDemoAssistant } from "../hooks/use-demo-assistant";
import { useMediaQuery } from "../hooks/use-media-query";
import { useScrollToLatest } from "../hooks/use-scroll-to-latest";
import { ANSWER_SOUND_LABEL, sphereStatus } from "../model/copy";
import { DEMO_NOW } from "../model/mock-data";
import { formatDayMonth, formatShortWeekday, formatTime, nextEvent } from "../model/format";
import type { DemoStateId } from "../model/types";
import { AsciiSphere } from "./ascii-sphere";
import { ConsoleDay } from "./console-day";
import { ConsoleLog } from "./console-log";
import { ConsolePrompt, LevelMeter } from "./console-prompt";
import { styles } from "./styles";
import { consoleMono } from "./fonts";

type Tab = "log" | "day";
const TABS: ReadonlyArray<{ id: Tab; label: string; index: number }> = [
  { id: "log", label: "диалог", index: 0 },
  { id: "day", label: "день", index: 1 },
];

const SUBLINES: Record<string, string> = {
  idle: "нажмите «говорить» или пишите в строке ниже",
  listening: "говорите — остановлюсь сам после паузы",
  thinking: "секунду",
  speaking: "звук можно выключить в строке состояния",
  waiting: "ответьте голосом, текстом или кнопкой",
  error: "запишите ещё раз или напишите текстом",
};

/** Вариант 1 «Консоль»: интерфейс как сессия tmux — сфера, лог и день в панелях. */
export function ConsoleScreen({
  initialState,
  showBar,
}: {
  initialState: DemoStateId;
  showBar: boolean;
}) {
  const assistant = useDemoAssistant(initialState);
  const [tab, setTab] = useState<Tab>("log");
  // На десктопе обе панели видны сразу — роли вкладок нужны только на узком экране.
  const tabbed = !useMediaQuery("(min-width: 64rem)");
  const inputRef = useRef<HTMLInputElement | null>(null);
  const logRef = useScrollToLatest<HTMLDivElement>(
    `${assistant.messages.length}-${assistant.phase.name}`,
  );
  const status = sphereStatus(assistant.sphere, assistant.phase);
  const upcoming = nextEvent(assistant.feed);

  const focusInput = () => {
    setTab("log");
    requestAnimationFrame(() => inputRef.current?.focus());
  };

  const onTabKey = (event: KeyboardEvent<HTMLButtonElement>) => {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    const next: Tab = tab === "log" ? "day" : "log";
    setTab(next);
    document.getElementById(`v1-tab-${next}`)?.focus();
  };

  return (
    <div className={cn(styles.root, consoleMono.variable, "flex h-dvh flex-col")}>
      {showBar ? <DemoBar variant={1} current={assistant.preset} onJump={assistant.jump} /> : null}
      <SkipLink />
      <h1 className="sr-only">Горький — голосовой ассистент задач и встреч</h1>

      <main
        id={MAIN_CONTENT_ID}
        tabIndex={-1}
        className="grid min-h-0 flex-1 grid-cols-[minmax(0,1fr)] grid-rows-[auto_minmax(0,1fr)] gap-3 p-2 pt-4 outline-none sm:gap-5 sm:p-4 sm:pt-5 lg:grid-cols-[minmax(0,1fr)_minmax(19rem,26rem)] lg:grid-rows-[auto_minmax(0,1fr)]"
      >
        {/* Сфера: на телефоне — узкая полоса сверху, на десктопе — панель-монитор. */}
        <section aria-labelledby="v1-sphere-title" className={cn(styles.pane, "lg:col-start-1")}>
          <h2 id="v1-sphere-title" className={styles.paneTitle}>
            сфера
          </h2>
          <div className="flex items-center gap-3 px-3 pt-3 pb-2 sm:gap-6 sm:px-5 lg:pt-4">
            <AsciiSphere
              mode={assistant.sphere}
              levelRef={assistant.levelRef}
              className="h-24 w-32 shrink-0 sm:h-36 sm:w-52 lg:h-52 lg:w-80"
            />
            <div className="grid min-w-0 flex-1 gap-1.5">
              <p
                role="status"
                className={cn(
                  styles.bigState,
                  assistant.sphere === "error" && styles.danger,
                  assistant.sphere === "waiting" && styles.wait,
                )}
              >
                {status.toLowerCase()}
              </p>
              <LevelMeter assistant={assistant} />
              <p className={cn(styles.muted, "text-xs text-pretty sm:text-sm")}>
                {SUBLINES[assistant.sphere]}
              </p>
              {upcoming?.starts_at ? (
                <p className="text-xs sm:text-sm lg:hidden">
                  <span className={styles.muted}>дальше: </span>
                  {formatTime(upcoming.starts_at)} {upcoming.title}
                </p>
              ) : null}
            </div>
          </div>
        </section>

        <section
          id="v1-panel-log"
          aria-labelledby={tabbed ? "v1-tab-log" : "v1-log-title"}
          role={tabbed ? "tabpanel" : undefined}
          className={cn(
            styles.pane,
            "flex min-h-0 flex-col lg:col-start-1 lg:row-start-2",
            tab !== "log" && "max-lg:hidden",
          )}
        >
          <h2 id="v1-log-title" className={styles.paneTitle}>
            сессия
          </h2>
          <div
            ref={logRef}
            role="log"
            aria-label="История разговора"
            className={cn(
              styles.paper,
              styles.logText,
              "min-h-0 flex-1 overflow-y-auto overscroll-contain px-6 pt-5 pb-6 sm:px-8",
            )}
          >
            <ConsoleLog assistant={assistant} onFocusInput={focusInput} />
          </div>
          <ConsolePrompt assistant={assistant} inputRef={inputRef} />
        </section>

        <section
          id="v1-panel-day"
          aria-labelledby={tabbed ? "v1-tab-day" : "v1-day-title"}
          role={tabbed ? "tabpanel" : undefined}
          className={cn(
            styles.pane,
            "flex min-h-0 flex-col lg:col-start-2 lg:row-span-2 lg:row-start-1",
            tab !== "day" && "max-lg:hidden",
          )}
        >
          <h2 id="v1-day-title" className={styles.paneTitle}>
            план
          </h2>
          <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain">
            <ConsoleDay feed={assistant.feed} />
          </div>
        </section>
      </main>

      <footer className={cn(styles.statusBar, "flex shrink-0 items-stretch")}>
        <p className={cn(styles.brandSeg, "flex items-center px-3 max-sm:hidden")} translate="no">
          горький
        </p>
        <div role="tablist" aria-label="Окна" className="flex lg:hidden">
          {TABS.map(({ id, label, index }) => (
            <button
              key={id}
              id={`v1-tab-${id}`}
              type="button"
              role="tab"
              aria-selected={tab === id}
              aria-controls={`v1-panel-${id}`}
              tabIndex={tab === id ? 0 : -1}
              onClick={() => setTab(id)}
              onKeyDown={onTabKey}
              className={styles.tab}
            >
              {index}:{label}
            </button>
          ))}
        </div>
        <p className="hidden items-center gap-4 px-4 lg:flex">
          <span>
            <span className={styles.kbd}>Enter</span> отправить
          </span>
          <span>
            <span className={styles.kbd}>Esc</span> отменить запись
          </span>
        </p>
        <div className="ml-auto flex items-center gap-1 pr-1 lg:pr-2">
          <SettingsMenu
            soundOn={assistant.soundOn}
            onSoundChange={assistant.setSoundOn}
            trigger={
              <button type="button" className={cn(styles.tab, "lg:hidden")}>
                настройки
              </button>
            }
          />
          <label className={cn(styles.toggle, "max-lg:hidden")}>
            <input
              type="checkbox"
              checked={assistant.soundOn}
              onChange={(event) => assistant.setSoundOn(event.target.checked)}
              className="size-4 accent-(--status-deep)"
            />
            <span>{ANSWER_SOUND_LABEL.toLowerCase()}</span>
          </label>
          <ThemeChoice
            className="hidden items-center lg:flex"
            legendClassName="sr-only"
            optionClassName={styles.choice}
          />
          <p className="px-2 whitespace-nowrap max-lg:hidden">
            {formatTime(DEMO_NOW.toISOString())} {formatShortWeekday(DEMO_NOW)}{" "}
            {formatDayMonth(DEMO_NOW)}
          </p>
        </div>
      </footer>
    </div>
  );
}
