"use client";

import { type FormEvent, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Dialog, DialogClose, DialogContent, DialogFooter } from "@/components/ui/dialog";
import { TextField } from "@/components/ui/text-field";
import { useAsyncAction } from "@/hooks/use-async-action";

import { useProfile } from "../profile-context";

type DialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCloseAutoFocus?: (event: Event) => void;
};

export function RestoreProfileDialog({ open, onOpenChange, onCloseAutoFocus }: DialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        title="Войти по коду восстановления"
        description="Откроется профиль, к которому относится код. Текущий профиль останется на сервере."
        onCloseAutoFocus={onCloseAutoFocus}
      >
        <RestoreForm onRestored={() => onOpenChange(false)} />
      </DialogContent>
    </Dialog>
  );
}

function RestoreForm({ onRestored }: { onRestored: () => void }) {
  const { restoreProfile } = useProfile();
  const { run, pending, error } = useAsyncAction(restoreProfile);
  const [validationError, setValidationError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending) return;

    const code = String(new FormData(event.currentTarget).get("code") ?? "").trim();
    if (!code) {
      setValidationError("Введите код восстановления");
      inputRef.current?.focus();
      return;
    }

    setValidationError(null);
    if (await run(code)) {
      onRestored();
    } else {
      inputRef.current?.focus();
    }
  }

  return (
    <form noValidate onSubmit={handleSubmit}>
      <TextField
        ref={inputRef}
        name="code"
        label="Код восстановления"
        hint="Три слова и четыре цифры, которые показали при создании профиля. Регистр и разделители не важны."
        placeholder="сирень-лиса-кедр-4821"
        error={validationError ?? error?.message ?? null}
        autoComplete="off"
        autoCapitalize="none"
        autoCorrect="off"
        spellCheck={false}
        enterKeyHint="go"
        translate="no"
      />
      <DialogFooter>
        <DialogClose asChild>
          <Button>Отмена</Button>
        </DialogClose>
        <Button type="submit" variant="primary" aria-busy={pending || undefined}>
          {pending ? "Входим…" : "Войти"}
        </Button>
      </DialogFooter>
    </form>
  );
}
