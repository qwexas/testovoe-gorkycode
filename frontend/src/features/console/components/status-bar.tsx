"use client";

import { type KeyboardEvent, useRef, useSyncExternalStore } from "react";

import { ServerStatus } from "@/components/server-status";
import { ThemeChoice } from "@/components/theme-choice";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { tty } from "@/components/ui/tty";
import { ProfileMenuItems, useProfileDialogs } from "@/features/profile/components/profile-menu";
import { useNotificationState } from "@/features/reminders/hooks/use-notification-state";
import { useTheme } from "@/hooks/use-theme";
import { cn } from "@/lib/cn";
import { formatDayMonth, formatShortWeekday, formatTime } from "@/lib/format";
import { isThemePreference } from "@/lib/theme";

export type Tab = "log" | "day";

const TABS: ReadonlyArray<{ id: Tab; label: string; index: number }> = [
  { id: "log", label: "диалог", index: 0 },
  { id: "day", label: "день", index: 1 },
];

const SPEAK_LABEL = "озвучивать ответы";

const subscribeNever = () => () => undefined;

/** На Mac Alt называется Option и рисуется значком ⌥. */
function useRecordHotkeyLabel(): string {
  return useSyncExternalStore(
    subscribeNever,
    () => (/Mac|iPhone|iPad/.test(navigator.platform) ? "⌥M" : "Alt+M"),
    () => "Alt+M",
  );
}

/** Меню для узких экранов: тема, озвучка, уведомления и профиль (паттерн APG «меню»). */
function MobileMenu({
  speakReplies,
  onSpeakChange,
  openDialog,
}: {
  speakReplies: boolean;
  onSpeakChange: (value: boolean) => void;
  openDialog: ReturnType<typeof useProfileDialogs>["openDialog"];
}) {
  const triggerRef = useRef<HTMLButtonElement>(null);
  const { preference, setPreference } = useTheme();
  const notifications = useNotificationState();

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button ref={triggerRef} type="button" className={cn(tty.btn, "min-h-11 lg:hidden")}>
          меню <span aria-hidden="true">▴</span>
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent side="top" className="w-72">
        <DropdownMenuLabel className="text-fg-muted">Тема оформления</DropdownMenuLabel>
        <DropdownMenuRadioGroup
          value={preference}
          onValueChange={(value) => {
            if (isThemePreference(value)) setPreference(value);
          }}
        >
          <DropdownMenuRadioItem value="system">Как в системе</DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="light">Светлая</DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="dark">Тёмная</DropdownMenuRadioItem>
        </DropdownMenuRadioGroup>
        <DropdownMenuSeparator />
        <DropdownMenuCheckboxItem
          checked={speakReplies}
          onCheckedChange={(value) => onSpeakChange(value === true)}
        >
          Озвучивать ответы
        </DropdownMenuCheckboxItem>
        {notifications.state === "default" ? (
          <DropdownMenuItem onSelect={() => void notifications.request()}>
            Включить уведомления о напоминаниях
          </DropdownMenuItem>
        ) : null}
        <DropdownMenuSeparator />
        <ProfileMenuItems openDialog={openDialog} trigger={triggerRef} />
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

/** Меню профиля в статусной строке десктопа. */
function ProfileMenu({
  openDialog,
}: {
  openDialog: ReturnType<typeof useProfileDialogs>["openDialog"];
}) {
  const triggerRef = useRef<HTMLButtonElement>(null);
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button ref={triggerRef} type="button" className={tty.btn}>
          профиль <span aria-hidden="true">▴</span>
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent side="top" className="w-80">
        <ProfileMenuItems openDialog={openDialog} trigger={triggerRef} />
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function Sep() {
  return (
    <span aria-hidden="true" className={cn(tty.sep, "max-lg:hidden")}>
      │
    </span>
  );
}

/**
 * Статусная строка tmux: на десктопе — подсказки клавиш, озвучка, тема, профиль и часы;
 * на телефоне — вкладки «0:диалог / 1:день» (tablist со стрелками) и общее меню.
 */
export function StatusBar({
  tab,
  onTabChange,
  speakReplies,
  onSpeakChange,
  now,
}: {
  tab: Tab;
  onTabChange: (tab: Tab) => void;
  speakReplies: boolean;
  onSpeakChange: (value: boolean) => void;
  now: Date | null;
}) {
  const hotkey = useRecordHotkeyLabel();
  const { openDialog, dialogs } = useProfileDialogs();

  const onTabKey = (event: KeyboardEvent<HTMLButtonElement>) => {
    const keys = ["ArrowLeft", "ArrowRight", "Home", "End"];
    if (!keys.includes(event.key)) return;
    event.preventDefault();
    let next: Tab;
    if (event.key === "Home") next = "log";
    else if (event.key === "End") next = "day";
    else next = tab === "log" ? "day" : "log";
    onTabChange(next);
    document.getElementById(`tab-${next}`)?.focus();
  };

  return (
    <footer
      className={cn(tty.statusBar, "mx-2 mt-1 mb-2 flex shrink-0 items-stretch sm:mx-4 sm:mb-4")}
    >
      <p className={cn(tty.paneTitle, tty.brand)} translate="no">
        горький
      </p>
      <div role="tablist" aria-label="Окна" className="flex lg:hidden">
        {TABS.map(({ id, label, index }) => (
          <button
            key={id}
            id={`tab-${id}`}
            type="button"
            role="tab"
            aria-selected={tab === id}
            aria-controls={`panel-${id}`}
            tabIndex={tab === id ? 0 : -1}
            onClick={() => onTabChange(id)}
            onKeyDown={onTabKey}
            className={tty.tab}
          >
            {index}:{label}
          </button>
        ))}
      </div>
      <p className="hidden h-11 min-w-0 flex-1 flex-wrap items-center gap-x-5 overflow-hidden px-4 text-fg-muted xl:flex">
        <span className="flex h-11 items-center gap-[1ch] whitespace-nowrap">
          <kbd className={tty.kbd}>{hotkey}</kbd> говорить
        </span>
        <span className="flex h-11 items-center gap-[1ch] whitespace-nowrap">
          <kbd className={tty.kbd}>Enter</kbd> отправить
        </span>
        <span className="flex h-11 items-center gap-[1ch] whitespace-nowrap">
          <kbd className={tty.kbd}>Esc</kbd> отменить запись
        </span>
      </p>
      <div className="ml-auto flex shrink-0 items-center pr-1">
        <ServerStatus className="text-fg-muted" />
        <Sep />
        <label className={cn(tty.toggle, "mx-1 max-lg:hidden")}>
          <input
            type="checkbox"
            checked={speakReplies}
            onChange={(event) => onSpeakChange(event.target.checked)}
            className="sr-only"
          />
          <span aria-hidden="true" className={tty.check}>
            {speakReplies ? "[x]" : "[ ]"}
          </span>
          <span>{SPEAK_LABEL}</span>
        </label>
        <Sep />
        <ThemeChoice
          className="mx-1 hidden items-center gap-0.5 lg:flex"
          legendClassName="sr-only"
          optionClassName={tty.choice}
        />
        <Sep />
        <div className="mx-1 max-lg:hidden">
          <ProfileMenu openDialog={openDialog} />
        </div>
        <MobileMenu
          speakReplies={speakReplies}
          onSpeakChange={onSpeakChange}
          openDialog={openDialog}
        />
        {now ? (
          <>
            <Sep />
            <p className="px-3 whitespace-nowrap text-fg-muted max-lg:hidden">
              <time dateTime={now.toISOString()}>
                {formatTime(now)} {formatShortWeekday(now)} {formatDayMonth(now)}
              </time>
            </p>
          </>
        ) : null}
      </div>
      {dialogs}
    </footer>
  );
}
