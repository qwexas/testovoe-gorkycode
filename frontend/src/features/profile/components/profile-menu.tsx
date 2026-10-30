"use client";

import { type ReactNode, type RefObject, useCallback, useRef, useState } from "react";

import {
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
} from "@/components/ui/dropdown-menu";
import { CalendarIcon, DownloadIcon, KeyIcon, PlusIcon, TrashIcon } from "@/components/ui/icons";
import { apiErrorFromException } from "@/lib/api/errors";
import { formatCount, formatDate } from "@/lib/format";

import { CALENDAR_FILE_NAME, downloadCalendar } from "../api";
import { useProfile } from "../profile-context";
import type { ProfileStatus } from "../profile-state";
import { CalendarSubscriptionDialog } from "./calendar-subscription-dialog";
import { DeleteDataDialog } from "./delete-data-dialog";
import { NewProfileDialog } from "./new-profile-dialog";
import { RecoveryCodeDialog } from "./recovery-code-dialog";
import { RestoreProfileDialog } from "./restore-profile-dialog";

export type ProfileDialogId = "calendar" | "new-profile" | "restore" | "delete";

export type ProfileMenuControls = {
  /** открыть окно; фокус после закрытия вернётся на `returnFocusTo`. */
  openDialog: (id: ProfileDialogId, returnFocusTo: HTMLElement | null) => void;
  /** окна профиля — смонтировать один раз рядом с меню. */
  dialogs: ReactNode;
};

/**
 * окна профиля и код восстановления. Меню профиля бывает в двух местах (статусная строка
 * на десктопе и общее меню на телефоне), а окна — одни на всех.
 */
export function useProfileDialogs(): ProfileMenuControls {
  const { profile: profileStatus } = useProfile();
  const [openId, setOpenId] = useState<ProfileDialogId | null>(null);
  const returnFocusRef = useRef<HTMLElement | null>(null);
  const profile = profileStatus.status === "ready" ? profileStatus.profile : null;

  const openDialog = useCallback((id: ProfileDialogId, returnFocusTo: HTMLElement | null) => {
    returnFocusRef.current = returnFocusTo;
    setOpenId(id);
  }, []);

  // окна открыты пунктом меню, которого после закрытия уже нет: фокус — на кнопку меню.
  const onCloseAutoFocus = useCallback((event: Event) => {
    event.preventDefault();
    returnFocusRef.current?.focus();
  }, []);

  const dialogProps = (id: ProfileDialogId) => ({
    open: openId === id,
    onOpenChange: (open: boolean) => setOpenId(open ? id : null),
    onCloseAutoFocus,
  });

  const dialogs = (
    <>
      <CalendarSubscriptionDialog
        {...dialogProps("calendar")}
        subscriptionUrl={profile?.calendar_subscription_url ?? ""}
      />
      <NewProfileDialog {...dialogProps("new-profile")} hasCurrentProfile={profile !== null} />
      <RestoreProfileDialog {...dialogProps("restore")} />
      <DeleteDataDialog {...dialogProps("delete")} eventsCount={profile?.events_count ?? 0} />
      <RecoveryCodeDialog onCloseAutoFocus={onCloseAutoFocus} />
    </>
  );

  return { openDialog, dialogs };
}

function ProfileSummary({ status }: { status: ProfileStatus }) {
  switch (status.status) {
    case "loading":
      return <DropdownMenuLabel className="text-fg-muted">Загружаю профиль…</DropdownMenuLabel>;
    case "ready":
      return (
        <DropdownMenuLabel>
          <span className="block font-semibold">Анонимный профиль</span>
          <span className="mt-0.5 block text-fg-muted">
            Создан {formatDate(status.profile.created_at)}
          </span>
          <span className="block text-fg-muted">
            {formatCount(status.profile.events_count, {
              one: "запись",
              few: "записи",
              many: "записей",
            })}
          </span>
        </DropdownMenuLabel>
      );
    case "deleted":
      return (
        <DropdownMenuLabel>
          <span className="block font-semibold">Данные удалены</span>
          <span className="mt-0.5 block text-pretty text-fg-muted">
            Создайте новый профиль или войдите по коду.
          </span>
        </DropdownMenuLabel>
      );
    case "anonymous":
      return (
        <DropdownMenuLabel>Создайте профиль или войдите по коду восстановления.</DropdownMenuLabel>
      );
    case "failed":
      return (
        <DropdownMenuLabel>
          <span className="block font-semibold">Профиль не загрузился</span>
          <span className="mt-0.5 block text-pretty text-fg-muted">{status.error.message}</span>
        </DropdownMenuLabel>
      );
  }
}

/**
 * пункты меню профиля: сводка, календарь (.ics и подписка), новый профиль, вход по коду,
 * удаление данных. Вставляются в любой DropdownMenuContent.
 */
export function ProfileMenuItems({
  openDialog,
  trigger,
}: {
  openDialog: ProfileMenuControls["openDialog"];
  /** кнопка, открывшая меню: на неё вернётся фокус после окна. */
  trigger: RefObject<HTMLElement | null>;
}) {
  const { profile: status, notify } = useProfile();
  const ready = status.status === "ready";
  const [downloading, setDownloading] = useState(false);

  const download = async () => {
    if (downloading) return;
    setDownloading(true);
    try {
      await downloadCalendar();
      notify(`Календарь скачан: откройте файл ${CALENDAR_FILE_NAME} в приложении календаря.`);
    } catch (cause) {
      notify(`Календарь не скачался. ${apiErrorFromException(cause).message}`);
    } finally {
      setDownloading(false);
    }
  };

  return (
    <>
      <ProfileSummary status={status} />
      <DropdownMenuSeparator />
      <DropdownMenuItem disabled={!ready} onSelect={() => void download()}>
        <DownloadIcon />
        Скачать календарь (.ics)
      </DropdownMenuItem>
      <DropdownMenuItem disabled={!ready} onSelect={() => openDialog("calendar", trigger.current)}>
        <CalendarIcon />
        Подписка на календарь
      </DropdownMenuItem>
      <DropdownMenuSeparator />
      <DropdownMenuItem onSelect={() => openDialog("new-profile", trigger.current)}>
        <PlusIcon />
        Новый профиль
      </DropdownMenuItem>
      <DropdownMenuItem onSelect={() => openDialog("restore", trigger.current)}>
        <KeyIcon />
        Войти по коду
      </DropdownMenuItem>
      <DropdownMenuSeparator />
      <DropdownMenuItem
        variant="danger"
        disabled={!ready}
        onSelect={() => openDialog("delete", trigger.current)}
      >
        <TrashIcon />
        Удалить все мои данные
      </DropdownMenuItem>
    </>
  );
}
