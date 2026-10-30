"use client";

import { useState } from "react";

import { tty } from "@/components/ui/tty";
import { useAsyncAction } from "@/hooks/use-async-action";
import { cn } from "@/lib/cn";

import { useProfile } from "../profile-context";
import { RestoreProfileDialog } from "./restore-profile-dialog";

/**
 * строка в логе сессии, когда работать не с чем: данные удалены или профиль не
 * загрузился. Вместо истории — что случилось и одна команда, чтобы продолжить.
 */
export function ProfileNotice({ onRecovered }: { onRecovered?: () => void }) {
  const { profile, createProfile, reload } = useProfile();
  const create = useAsyncAction(createProfile);
  const retry = useAsyncAction(reload);
  const [restoring, setRestoring] = useState(false);

  if (profile.status === "deleted" || profile.status === "anonymous") {
    return (
      <div className="grid justify-items-start gap-1 pl-[3ch]">
        <p className={cn(tty.ok, "text-pretty")}>
          <span aria-hidden="true">✓ </span>
          {profile.status === "deleted"
            ? "Данные удалены: профиль, задачи, встречи и история диалога стёрты с сервера."
            : profile.reason === "expired"
              ? "Доступ к профилю утрачен. Войдите по коду восстановления."
              : "Создайте профиль или восстановите доступ по сохранённому коду."}
        </p>
        <p className={cn(tty.muted, "text-pretty")}>
          Чтобы продолжить, создайте новый профиль или войдите по коду в меню профиля внизу экрана.
        </p>
        {create.error ? (
          <p role="alert" className={tty.danger}>
            {create.error.message}
          </p>
        ) : null}
        <button
          type="button"
          aria-disabled={create.pending || undefined}
          onClick={async () => {
            if (create.pending) return;
            if (await create.run()) onRecovered?.();
          }}
          className={cn(tty.btn, "-ml-1.5")}
        >
          {create.pending ? "создаю профиль…" : "создать профиль"}
        </button>
        <button type="button" className={tty.btn} onClick={() => setRestoring(true)}>
          войти по коду
        </button>
        <RestoreProfileDialog open={restoring} onOpenChange={setRestoring} />
      </div>
    );
  }

  if (profile.status === "failed") {
    return (
      <div className="grid justify-items-start gap-1 pl-[3ch]">
        <p className={cn(tty.danger, "text-pretty")}>
          <span aria-hidden="true">✗ </span>
          Профиль не загрузился. {profile.error.message}
        </p>
        <button
          type="button"
          aria-disabled={retry.pending || undefined}
          onClick={async () => {
            if (retry.pending) return;
            if (await retry.run()) onRecovered?.();
          }}
          className={cn(tty.btn, "-ml-1.5")}
        >
          {retry.pending ? "загружаю…" : "загрузить снова"}
        </button>
      </div>
    );
  }

  return null;
}
