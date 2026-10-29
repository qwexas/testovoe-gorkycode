"use client";

import { useCallback, useMemo, useRef, useState } from "react";

import { MAIN_CONTENT_ID, SkipLink } from "@/components/skip-link";
import { tty } from "@/components/ui/tty";
import { PromptLine } from "@/features/assistant/components/prompt-line";
import { SessionLog } from "@/features/assistant/components/session-log";
import { useAssistant } from "@/features/assistant/hooks/use-assistant";
import { useScrollToLatest } from "@/features/assistant/hooks/use-scroll-to-latest";
import { createNotice } from "@/features/assistant/model/conversation";
import { DayPlanView } from "@/features/events/components/day-plan";
import { useDayPlan } from "@/features/events/hooks/use-day-plan";
import { nextEvent } from "@/features/events/model/event-format";
import { ProfileNotice } from "@/features/profile/components/profile-notice";
import { useProfile } from "@/features/profile/profile-context";
import { NotificationsNote } from "@/features/reminders/components/notifications-note";
import { type Alarm, useReminders } from "@/features/reminders/hooks/use-reminders";
import { useAudioUnlock } from "@/hooks/use-audio-unlock";
import { useMediaQuery } from "@/hooks/use-media-query";
import { useNow } from "@/hooks/use-now";
import { cn } from "@/lib/cn";
import { dayOffset, formatTime } from "@/lib/format";

import { StatusBar, type Tab } from "./status-bar";
import { SpherePane } from "./sphere-pane";

/**
 * Главный экран «Консоль» (решение Q8): сессия tmux — сфера голоса, лог разговора со
 * строкой `$`, план дня справа и статусная строка. На телефоне — вкладки «0:диалог / 1:день».
 */
export function ConsoleScreen() {
  const { profile } = useProfile();
  const profileId = profile.status === "ready" ? profile.profile.id : null;
  const now = useNow();
  const { plan, refresh: refreshPlan } = useDayPlan(profileId, now);
  const assistant = useAssistant({ profileId, onEventsChanged: refreshPlan });
  const [tab, setTab] = useState<Tab>("log");
  // На десктопе обе панели видны сразу — роли вкладок нужны только на узком экране.
  const tabbed = !useMediaQuery("(min-width: 64rem)");
  const inputRef = useRef<HTMLInputElement | null>(null);
  useAudioUnlock();

  const { addNotice } = assistant;
  const onAlarm = useCallback(
    (alarm: Alarm) => addNotice(createNotice(alarm.text, "alarm")),
    [addNotice],
  );
  const planEvents = plan.status === "ready" ? plan.events : null;
  useReminders({ events: planEvents, now, onAlarm });

  const { entries, activity } = assistant.conversation;
  const lastKey = entries.at(-1)?.key ?? "";
  const logRef = useScrollToLatest<HTMLDivElement>(`${lastKey}-${activity.name}`, tab);

  const focusInput = useCallback(() => {
    setTab("log");
    // Вкладка «диалог» на телефоне показывается после перерисовки — фокусируем следующим кадром.
    requestAnimationFrame(() => inputRef.current?.focus());
  }, []);

  const upcoming = useMemo(() => {
    if (!planEvents || !now) return null;
    const event = nextEvent(planEvents, now);
    if (!event?.starts_at) return null;
    const day = dayOffset(event.starts_at, now) === 1 ? "завтра " : "";
    return `${day}${formatTime(event.starts_at)} ${event.title}`;
  }, [planEvents, now]);

  const freshIds = useMemo(
    () => new Set(assistant.conversation.changedIds),
    [assistant.conversation.changedIds],
  );

  const profileBlocked = profile.status !== "ready" && profile.status !== "loading";

  return (
    <div className={cn(tty.root, "flex h-dvh flex-col")}>
      <SkipLink />
      <h1 className="sr-only">Горький — голосовой ассистент задач и встреч</h1>

      <main
        id={MAIN_CONTENT_ID}
        tabIndex={-1}
        className="grid min-h-0 flex-1 grid-cols-[minmax(0,1fr)] grid-rows-[auto_minmax(0,1fr)] gap-3 p-2 pt-4 outline-none sm:gap-5 sm:p-4 sm:pt-5 lg:grid-cols-[minmax(0,1fr)_minmax(19rem,26rem)]"
      >
        <SpherePane assistant={assistant} upcoming={upcoming} />

        <section
          id="panel-log"
          aria-labelledby={tabbed ? "tab-log" : "log-title"}
          role={tabbed ? "tabpanel" : undefined}
          className={cn(
            tty.pane,
            "flex min-h-0 flex-col lg:col-start-1 lg:row-start-2",
            tab !== "log" && "max-lg:hidden",
          )}
        >
          <h2 id="log-title" className={tty.paneTitle}>
            сессия
          </h2>
          <div
            ref={logRef}
            role="log"
            aria-label="История разговора"
            // Озвучиваются только новые реплики, а не тикающие «через 20 минут» и отсчёт отмены.
            aria-relevant="additions"
            className={cn(
              tty.paper,
              tty.logText,
              "relative min-h-0 flex-1 overflow-y-auto overscroll-contain px-6 pt-5 pb-6 sm:px-8",
            )}
          >
            {profileBlocked ? (
              <ProfileNotice onRecovered={focusInput} />
            ) : (
              <SessionLog assistant={assistant} now={now} handlers={{ focusInput }} />
            )}
          </div>
          <PromptLine assistant={assistant} inputRef={inputRef} />
        </section>

        <section
          id="panel-day"
          aria-labelledby={tabbed ? "tab-day" : "day-title"}
          role={tabbed ? "tabpanel" : undefined}
          className={cn(
            tty.pane,
            "flex min-h-0 flex-col lg:col-start-2 lg:row-span-2 lg:row-start-1",
            tab !== "day" && "max-lg:hidden",
          )}
        >
          <h2 id="day-title" className={tty.paneTitle}>
            план
          </h2>
          <div className="relative min-h-0 flex-1 overflow-y-auto overscroll-contain">
            <DayPlanView
              plan={plan}
              now={now}
              freshIds={freshIds}
              onRetry={refreshPlan}
              footer={<NotificationsNote />}
            />
          </div>
        </section>
      </main>

      <StatusBar
        tab={tab}
        onTabChange={setTab}
        speakReplies={assistant.speakReplies}
        onSpeakChange={assistant.setSpeakReplies}
        now={now}
      />
    </div>
  );
}
