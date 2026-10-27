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
        <button ref={triggerRef} type="button" className={cn(tty.tab, "lg:hidden")}>
          меню
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
        <button ref={triggerRef} type="button" className={cn(tty.tab, "max-lg:hidden")}>
          профиль <span aria-hidden="true">▴</span>
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent side="top" className="w-80">
        <ProfileMenuItems openDialog={openDialog} trigger={triggerRef} />
      </DropdownMenuContent>
    </DropdownMenu>
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
    <footer className={cn(tty.statusBar, "flex shrink-0 items-stretch")}>
      <p className={cn(tty.brandSeg, "flex items-center px-3 max-sm:hidden")} translate="no">
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
      <p className="hidden items-center gap-4 px-4 xl:flex">
        <span>
          <kbd className={tty.kbd}>{hotkey}</kbd> говорить
        </span>
        <span>
          <kbd className={tty.kbd}>Enter</kbd> отправить
        </span>
        <span>
          <kbd className={tty.kbd}>Esc</kbd> отменить запись
        </span>
      </p>
      <div className="ml-auto flex items-center pr-1 lg:pr-2">
        <ServerStatus />
        <label className={cn(tty.toggle, "max-lg:hidden")}>
          <input
            type="checkbox"
            checked={speakReplies}
            onChange={(event) => onSpeakChange(event.target.checked)}
            className="size-4 accent-(--status-deep)"
          />
          <span>{SPEAK_LABEL}</span>
        </label>
        <ThemeChoice
          className="hidden items-center lg:flex"
          legendClassName="sr-only"
          optionClassName={tty.choice}
        />
        <ProfileMenu openDialog={openDialog} />
        <MobileMenu
          speakReplies={speakReplies}
          onSpeakChange={onSpeakChange}
          openDialog={openDialog}
        />
        {now ? (
          <p className="px-2 whitespace-nowrap max-lg:hidden">
            <time dateTime={now.toISOString()}>
              {formatTime(now)} {formatShortWeekday(now)} {formatDayMonth(now)}
            </time>
          </p>
        ) : null}
      </div>
      {dialogs}
    </footer>
  );
}
