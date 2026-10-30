"use client";

import * as RadixDialog from "@radix-ui/react-dialog";
import type { ComponentProps, ReactNode } from "react";

import { cn } from "@/lib/cn";

import { Button } from "./button";
import { CloseIcon } from "./icons";

export const Dialog = RadixDialog.Root;
export const DialogClose = RadixDialog.Close;

type DialogContentProps = Omit<ComponentProps<typeof RadixDialog.Content>, "title"> & {
  title: string;
  description?: ReactNode;
};

/**
 * модальное окно: фокус внутри, Esc и клик по фону закрывают, фон недоступен.
 * Заголовок обязателен — он же доступное имя окна.
 */
export function DialogContent({
  title,
  description,
  children,
  className,
  ...props
}: DialogContentProps) {
  return (
    <RadixDialog.Portal>
      <RadixDialog.Overlay className="fixed inset-0 z-40 bg-overlay motion-safe:data-[state=open]:animate-overlay-in" />
      <RadixDialog.Content
        className={cn(
          "fixed top-1/2 left-1/2 z-50 w-[calc(100vw-2rem)] max-w-md -translate-x-1/2 -translate-y-1/2",
          "max-h-[calc(100dvh-2rem)] overflow-y-auto overscroll-contain",
          "border border-border-strong bg-surface p-6 text-fg",
          "motion-safe:data-[state=open]:animate-dialog-in",
          className,
        )}
        {...(description ? {} : { "aria-describedby": undefined })}
        {...props}
      >
        <RadixDialog.Title className="pr-10 text-lg leading-snug font-semibold text-balance [font-stretch:112.5%]">
          {title}
        </RadixDialog.Title>
        {description ? (
          <RadixDialog.Description className="mt-2 text-sm leading-relaxed text-pretty text-fg-muted">
            {description}
          </RadixDialog.Description>
        ) : null}
        <div className="mt-5">{children}</div>
        <RadixDialog.Close asChild>
          <Button
            variant="ghost"
            size="icon"
            aria-label="Закрыть окно"
            className="absolute top-3 right-3"
          >
            <CloseIcon />
          </Button>
        </RadixDialog.Close>
      </RadixDialog.Content>
    </RadixDialog.Portal>
  );
}

export function DialogFooter({ className, ...props }: ComponentProps<"div">) {
  return (
    <div
      className={cn("mt-6 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end", className)}
      {...props}
    />
  );
}
