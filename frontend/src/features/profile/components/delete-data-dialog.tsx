"use client";

import { Button } from "@/components/ui/button";
import { Dialog, DialogClose, DialogContent, DialogFooter } from "@/components/ui/dialog";
import { FormError } from "@/components/ui/form-error";
import { useAsyncAction } from "@/hooks/use-async-action";
import { formatCount } from "@/lib/format";

import { useProfile } from "../profile-context";

type DialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCloseAutoFocus?: (event: Event) => void;
  eventsCount: number;
};

/** «Удалить все мои данные» (решение Q35). Необратимо, поэтому всегда переспрашиваем. */
export function DeleteDataDialog({
  open,
  onOpenChange,
  onCloseAutoFocus,
  eventsCount,
}: DialogProps) {
  const records = formatCount(eventsCount, { one: "запись", few: "записи", many: "записей" });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        role="alertdialog"
        title="Удалить все мои данные?"
        description={`Удалим профиль, ${records} и историю диалога. Восстановить их будет нельзя, код восстановления перестанет работать.`}
        onCloseAutoFocus={onCloseAutoFocus}
      >
        <DeleteActions onDeleted={() => onOpenChange(false)} />
      </DialogContent>
    </Dialog>
  );
}

function DeleteActions({ onDeleted }: { onDeleted: () => void }) {
  const { deleteAllData } = useProfile();
  const { run, pending, error } = useAsyncAction(deleteAllData);

  async function handleDelete() {
    if (pending) return;
    if (await run()) onDeleted();
  }

  return (
    <>
      <FormError message={error?.message ?? null} />
      <DialogFooter>
        <DialogClose asChild>
          <Button>Отмена</Button>
        </DialogClose>
        <Button variant="danger" aria-busy={pending || undefined} onClick={handleDelete}>
          {pending ? "Удаляем данные…" : "Удалить данные"}
        </Button>
      </DialogFooter>
    </>
  );
}
