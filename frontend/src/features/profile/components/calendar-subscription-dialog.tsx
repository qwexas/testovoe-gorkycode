"use client";

import { CopyButton } from "@/components/copy-button";
import { Button, buttonClasses } from "@/components/ui/button";
import { Dialog, DialogClose, DialogContent, DialogFooter } from "@/components/ui/dialog";
import { TextField } from "@/components/ui/text-field";

type DialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCloseAutoFocus?: (event: Event) => void;
  subscriptionUrl: string;
};

/** Ссылка-подписка webcal:// с секретным токеном (решение Q27). */
export function CalendarSubscriptionDialog({
  open,
  onOpenChange,
  onCloseAutoFocus,
  subscriptionUrl,
}: DialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        title="Подписка на календарь"
        description="Добавьте ссылку в календарь на телефоне или компьютере: задачи, встречи и напоминания появятся там и будут обновляться сами."
        onCloseAutoFocus={onCloseAutoFocus}
        className="sm:max-w-lg"
      >
        <TextField
          label="Ссылка для подписки"
          value={subscriptionUrl}
          readOnly
          onFocus={(event) => event.currentTarget.select()}
          hint="Ссылка секретная: по ней видны все ваши записи. Не публикуйте её."
          translate="no"
          className="font-mono text-sm"
        />
        <CopyButton value={subscriptionUrl} label="Скопировать ссылку" className="mt-4" />
        <DialogFooter>
          <a href={subscriptionUrl} className={buttonClasses()}>
            Открыть в приложении календаря
          </a>
          <DialogClose asChild>
            <Button variant="primary">Готово</Button>
          </DialogClose>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
