"use client";

import { Button } from "@/components/ui/button";
import { Dialog, DialogClose, DialogContent, DialogFooter } from "@/components/ui/dialog";
import { FormError } from "@/components/ui/form-error";
import { useAsyncAction } from "@/hooks/use-async-action";

import { useProfile } from "../profile-context";

type DialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCloseAutoFocus?: (event: Event) => void;
  /** false — профиля нет (данные удалены или не загрузились): предупреждать не о чем. */
  hasCurrentProfile: boolean;
};

/** «Новый профиль»: переключает cookie на свежий профиль, старый остаётся на сервере. */
export function NewProfileDialog({
  open,
  onOpenChange,
  onCloseAutoFocus,
  hasCurrentProfile,
}: DialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        title="Создать новый профиль?"
        description={
          hasCurrentProfile
            ? "Задачи и встречи текущего профиля останутся на сервере. Вернуться к ним можно только по коду восстановления."
            : "Создадим профиль и покажем код восстановления. Сохраните его, чтобы не потерять доступ."
        }
        onCloseAutoFocus={onCloseAutoFocus}
      >
        <NewProfileActions onCreated={() => onOpenChange(false)} />
      </DialogContent>
    </Dialog>
  );
}

function NewProfileActions({ onCreated }: { onCreated: () => void }) {
  const { createProfile } = useProfile();
  const { run, pending, error } = useAsyncAction(createProfile);

  async function handleCreate() {
    if (pending) return;
    if (await run()) onCreated();
  }

  return (
    <>
      <FormError message={error?.message ?? null} />
      <DialogFooter>
        <DialogClose asChild>
          <Button>Отмена</Button>
        </DialogClose>
        <Button variant="primary" aria-busy={pending || undefined} onClick={handleCreate}>
          {pending ? "Создаём профиль…" : "Создать профиль"}
        </Button>
      </DialogFooter>
    </>
  );
}
