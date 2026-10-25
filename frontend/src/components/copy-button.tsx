"use client";

import { useCopyToClipboard } from "@/hooks/use-copy-to-clipboard";
import { cn } from "@/lib/cn";

import { Button, type ButtonVariant } from "./ui/button";
import { CheckIcon, CopyIcon } from "./ui/icons";

/** Кнопка копирования; результат пишется рядом и озвучивается экранным диктором. */
export function CopyButton({
  value,
  label,
  variant = "secondary",
  className,
}: {
  value: string;
  label: string;
  variant?: ButtonVariant;
  className?: string;
}) {
  const { status, copy } = useCopyToClipboard();

  return (
    <div className={cn("flex flex-wrap items-center gap-x-3 gap-y-2", className)}>
      <Button variant={variant} onClick={() => void copy(value)}>
        {status === "copied" ? <CheckIcon /> : <CopyIcon />}
        {label}
      </Button>
      <p
        role="status"
        className={cn(
          "text-sm text-pretty",
          status === "failed" ? "basis-full text-danger" : "text-fg-muted",
        )}
      >
        {status === "copied" ? "Скопировано" : null}
        {status === "failed"
          ? "Не получилось скопировать. Выделите текст и скопируйте вручную."
          : null}
      </p>
    </div>
  );
}
