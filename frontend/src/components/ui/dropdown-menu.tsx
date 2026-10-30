"use client";

import * as RadixMenu from "@radix-ui/react-dropdown-menu";
import type { ComponentProps } from "react";

import { cn } from "@/lib/cn";

import { CheckIcon } from "./icons";

/*
 * меню по паттерну APG: стрелки двигают выделение, Enter/пробел выбирают, Esc закрывает
 * и возвращает фокус на кнопку. modal={false} по умолчанию: меню открывает модальные
 * окна, а модальное меню поверх модального окна оставляет body без pointer-events.
 */
export function DropdownMenu({ modal = false, ...props }: ComponentProps<typeof RadixMenu.Root>) {
  return <RadixMenu.Root modal={modal} {...props} />;
}

export const DropdownMenuTrigger = RadixMenu.Trigger;
export const DropdownMenuRadioGroup = RadixMenu.RadioGroup;

export function DropdownMenuContent({
  className,
  sideOffset = 8,
  align = "end",
  collisionPadding = 16,
  ...props
}: ComponentProps<typeof RadixMenu.Content>) {
  return (
    <RadixMenu.Portal>
      <RadixMenu.Content
        sideOffset={sideOffset}
        align={align}
        collisionPadding={collisionPadding}
        className={cn(
          "z-50 min-w-56 border border-border-strong bg-surface p-1 text-fg shadow-lg",
          "max-h-(--radix-dropdown-menu-content-available-height) overflow-y-auto overscroll-contain",
          "motion-safe:data-[state=open]:animate-menu-in",
          className,
        )}
        {...props}
      />
    </RadixMenu.Portal>
  );
}

// outline-hidden — прозрачная обводка: в режиме высокой контрастности она становится видимой
// и показывает выделенный пункт, когда фоновая подсветка пропадает.
const ITEM_CLASSES =
  "relative flex min-h-10 cursor-default items-center gap-3 px-3 text-sm outline-hidden select-none " +
  "data-disabled:pointer-events-none data-disabled:opacity-50 " +
  "data-highlighted:bg-accent-fill data-highlighted:text-on-accent";

export function DropdownMenuItem({
  className,
  variant = "default",
  ...props
}: ComponentProps<typeof RadixMenu.Item> & { variant?: "default" | "danger" }) {
  return (
    <RadixMenu.Item
      className={cn(
        ITEM_CLASSES,
        variant === "danger" &&
          "text-danger data-highlighted:bg-danger-fill data-highlighted:text-on-danger",
        className,
      )}
      {...props}
    />
  );
}

export function DropdownMenuRadioItem({
  className,
  children,
  ...props
}: ComponentProps<typeof RadixMenu.RadioItem>) {
  return (
    <RadixMenu.RadioItem className={cn(ITEM_CLASSES, "pr-9", className)} {...props}>
      {children}
      <RadixMenu.ItemIndicator className="absolute right-3 inline-flex">
        <CheckIcon size={16} />
      </RadixMenu.ItemIndicator>
    </RadixMenu.RadioItem>
  );
}

export function DropdownMenuCheckboxItem({
  className,
  children,
  ...props
}: ComponentProps<typeof RadixMenu.CheckboxItem>) {
  return (
    <RadixMenu.CheckboxItem className={cn(ITEM_CLASSES, "pr-9", className)} {...props}>
      {children}
      <RadixMenu.ItemIndicator className="absolute right-3 inline-flex">
        <CheckIcon size={16} />
      </RadixMenu.ItemIndicator>
    </RadixMenu.CheckboxItem>
  );
}

export function DropdownMenuLabel({ className, ...props }: ComponentProps<typeof RadixMenu.Label>) {
  return <RadixMenu.Label className={cn("px-3 py-2 text-sm", className)} {...props} />;
}

export function DropdownMenuSeparator({
  className,
  ...props
}: ComponentProps<typeof RadixMenu.Separator>) {
  return (
    <RadixMenu.Separator className={cn("mx-1.5 my-1.5 h-px bg-border", className)} {...props} />
  );
}
