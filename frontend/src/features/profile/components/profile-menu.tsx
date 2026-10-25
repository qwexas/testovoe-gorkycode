"use client";

import { useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  CalendarIcon,
  ChevronDownIcon,
  KeyIcon,
  PlusIcon,
  TrashIcon,
  UserIcon,
} from "@/components/ui/icons";
import { formatCount, formatDate } from "@/lib/format";

import { useProfile } from "../profile-context";
import type { ProfileStatus } from "../profile-state";
import { CalendarSubscriptionDialog } from "./calendar-subscription-dialog";
import { DeleteDataDialog } from "./delete-data-dialog";
import { NewProfileDialog } from "./new-profile-dialog";
import { RecoveryCodeDialog } from "./recovery-code-dialog";
import { RestoreProfileDialog } from "./restore-profile-dialog";

type OpenDialog = "calendar" | "new-profile" | "restore" | "delete" | null;

/** Меню профиля в шапке и все окна, которые из него открываются. */
export function ProfileMenu() {
  const { profile: profileStatus } = useProfile();
  const [openDialog, setOpenDialog] = useState<OpenDialog>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);

  const profile = profileStatus.status === "ready" ? profileStatus.profile : null;

  const dialogProps = (id: Exclude<OpenDialog, null>) => ({
    open: openDialog === id,
    onOpenChange: (open: boolean) => setOpenDialog(open ? id : null),
    // Окна открыты не своим триггером, а пунктом меню, которого после закрытия уже нет.
    // Возвращаем фокус на кнопку «Профиль».
    onCloseAutoFocus: (event: Event) => {
      event.preventDefault();
      triggerRef.current?.focus();
    },
  });

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            ref={triggerRef}
            variant="secondary"
            aria-busy={profileStatus.status === "loading" || undefined}
            className="w-10 px-0 sm:w-auto sm:px-3"
          >
            <UserIcon />
            {/* На узком экране — только иконка; имя кнопки остаётся «Профиль». */}
            <span className="sr-only sm:not-sr-only">Профиль</span>
            <ChevronDownIcon size={16} className="hidden text-fg-muted sm:block" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent className="w-72">
          <ProfileSummary status={profileStatus} />
          <DropdownMenuSeparator />
          <DropdownMenuItem disabled={!profile} onSelect={() => setOpenDialog("calendar")}>
            <CalendarIcon />
            Подписка на календарь
          </DropdownMenuItem>
          <DropdownMenuItem onSelect={() => setOpenDialog("new-profile")}>
            <PlusIcon />
            Новый профиль
          </DropdownMenuItem>
          <DropdownMenuItem onSelect={() => setOpenDialog("restore")}>
            <KeyIcon />
            Войти по коду
          </DropdownMenuItem>
          <DropdownMenuSeparator />
          <DropdownMenuItem
            variant="danger"
            disabled={!profile}
            onSelect={() => setOpenDialog("delete")}
          >
            <TrashIcon />
            Удалить все мои данные
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>

      <CalendarSubscriptionDialog
        {...dialogProps("calendar")}
        subscriptionUrl={profile?.calendar_subscription_url ?? ""}
      />
      <NewProfileDialog {...dialogProps("new-profile")} hasCurrentProfile={profile !== null} />
      <RestoreProfileDialog {...dialogProps("restore")} />
      <DeleteDataDialog {...dialogProps("delete")} eventsCount={profile?.events_count ?? 0} />
      <RecoveryCodeDialog onCloseAutoFocus={dialogProps("new-profile").onCloseAutoFocus} />
    </>
  );
}

function ProfileSummary({ status }: { status: ProfileStatus }) {
  switch (status.status) {
    case "loading":
      return <DropdownMenuLabel className="text-fg-muted">Загружаем профиль…</DropdownMenuLabel>;
    case "ready":
      return (
        <DropdownMenuLabel>
          <span className="block font-medium">Анонимный профиль</span>
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
          <span className="block font-medium">Данные удалены</span>
          <span className="mt-0.5 block text-pretty text-fg-muted">
            Создайте новый профиль или войдите по коду.
          </span>
        </DropdownMenuLabel>
      );
    case "failed":
      return (
        <DropdownMenuLabel>
          <span className="block font-medium">Профиль не загрузился</span>
          <span className="mt-0.5 block text-pretty text-fg-muted">{status.error.message}</span>
        </DropdownMenuLabel>
      );
  }
}
