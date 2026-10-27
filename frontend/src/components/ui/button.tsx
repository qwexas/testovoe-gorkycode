import type { ComponentProps } from "react";

import { cn } from "@/lib/cn";

export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
export type ButtonSize = "sm" | "md" | "icon";

const VARIANT_CLASSES: Record<ButtonVariant, string> = {
  primary: "bg-accent-fill text-on-accent hover:bg-accent-fill-hover",
  secondary: "border border-border-strong bg-surface text-fg hover:bg-surface-raised",
  ghost: "text-fg hover:bg-surface-raised",
  danger: "bg-danger-fill text-on-danger hover:bg-danger-fill-hover",
};

const SIZE_CLASSES: Record<ButtonSize, string> = {
  sm: "h-9 px-3 text-sm",
  md: "h-10 px-4 text-sm",
  icon: "size-10",
};

export type ButtonProps = ComponentProps<"button"> & {
  variant?: ButtonVariant;
  size?: ButtonSize;
};

/** Классы кнопки — и для <a>, который должен выглядеть как кнопка. */
export function buttonClasses({
  variant = "secondary",
  size = "md",
  className,
}: { variant?: ButtonVariant; size?: ButtonSize; className?: string } = {}): string {
  return cn(
    "inline-flex shrink-0 touch-manipulation items-center justify-center gap-2 font-medium whitespace-nowrap transition-colors select-none",
    "disabled:cursor-not-allowed disabled:opacity-50 aria-busy:cursor-progress",
    VARIANT_CLASSES[variant],
    SIZE_CLASSES[size],
    className,
  );
}

/**
 * Кнопка. Пока идёт запрос, ставьте aria-busy вместо disabled: отключённая кнопка
 * теряет фокус, и клавиатурный пользователь оказывается в начале страницы.
 */
export function Button({ variant, size, type = "button", className, ...props }: ButtonProps) {
  return <button type={type} className={buttonClasses({ variant, size, className })} {...props} />;
}
