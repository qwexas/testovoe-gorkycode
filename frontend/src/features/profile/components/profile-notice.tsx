"use client";

import { MAIN_CONTENT_ID } from "@/components/skip-link";
import { Button } from "@/components/ui/button";
import { FormError } from "@/components/ui/form-error";
import { useAsyncAction } from "@/hooks/use-async-action";

import { useProfile } from "../profile-context";

/** Сообщение в основной зоне, когда работать не с чем: данные удалены или профиль не загрузился. */
export function ProfileNotice() {
  const { profile, createProfile, reload } = useProfile();
  const create = useAsyncAction(createProfile);
  const retry = useAsyncAction(reload);

  if (profile.status === "deleted") {
    return (
      <section
        aria-labelledby="profile-notice-title"
        className="rounded-2xl border border-border bg-surface p-5"
      >
        <h2 id="profile-notice-title" className="font-semibold">
          Данные удалены
        </h2>
        <p className="mt-1 text-sm text-pretty text-fg-muted">
          Профиль, задачи, встречи и история диалога стёрты с сервера. Чтобы продолжить, создайте
          новый профиль или войдите по коду через меню «Профиль».
        </p>
        <FormError message={create.error?.message ?? null} />
        <Button
          variant="primary"
          className="mt-4"
          aria-busy={create.pending || undefined}
          onClick={() => {
            if (!create.pending) void create.run();
          }}
        >
          {create.pending ? "Создаём профиль…" : "Создать профиль"}
        </Button>
      </section>
    );
  }

  if (profile.status === "failed") {
    return (
      <section
        aria-labelledby="profile-notice-title"
        className="rounded-2xl border border-border bg-surface p-5"
      >
        <h2 id="profile-notice-title" className="font-semibold">
          Профиль не загрузился
        </h2>
        <p className="mt-1 text-sm text-pretty text-fg-muted">{profile.error.message}</p>
        <Button
          className="mt-4"
          aria-busy={retry.pending || undefined}
          onClick={async () => {
            if (retry.pending) return;
            // При успехе блок исчезнет вместе с кнопкой — переносим фокус в основную зону.
            if (await retry.run()) document.getElementById(MAIN_CONTENT_ID)?.focus();
          }}
        >
          {retry.pending ? "Загружаем…" : "Загрузить снова"}
        </Button>
      </section>
    );
  }

  return null;
}
