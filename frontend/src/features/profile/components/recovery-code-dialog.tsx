"use client";

import { CopyButton } from "@/components/copy-button";
import { Button } from "@/components/ui/button";
import { Dialog, DialogClose, DialogContent, DialogFooter } from "@/components/ui/dialog";

import { useProfile } from "../profile-context";

/** Код восстановления: сервер отдаёт его только при создании профиля, показываем один раз. */
export function RecoveryCodeDialog({
  onCloseAutoFocus,
}: {
  onCloseAutoFocus?: (event: Event) => void;
}) {
  const { pendingRecoveryCode, dismissRecoveryCode } = useProfile();

  return (
    <Dialog
      open={pendingRecoveryCode !== null}
      onOpenChange={(open) => {
        if (!open) dismissRecoveryCode();
      }}
    >
      <DialogContent
        title="Сохраните код восстановления"
        description="По этому коду вы вернётесь к своим задачам и встречам на другом устройстве или после очистки браузера. Код показывается только один раз."
        onCloseAutoFocus={onCloseAutoFocus}
      >
        <p
          translate="no"
          className="rounded-xl border border-border-strong bg-bg px-4 py-4 text-center font-mono text-lg font-medium break-words select-all"
        >
          {pendingRecoveryCode}
        </p>
        <CopyButton value={pendingRecoveryCode ?? ""} label="Скопировать код" className="mt-4" />
        <DialogFooter>
          <DialogClose asChild>
            <Button variant="primary">Готово</Button>
          </DialogClose>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
