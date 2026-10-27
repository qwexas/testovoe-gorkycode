import { type ComponentProps, useId } from "react";

import { cn } from "@/lib/cn";

type TextFieldProps = ComponentProps<"input"> & {
  label: string;
  hint?: string;
  error?: string | null;
};

/** Поле с видимой подписью; подсказка и ошибка связаны через aria-describedby. */
export function TextField({ label, hint, error, id, className, ...props }: TextFieldProps) {
  const generatedId = useId();
  const inputId = id ?? generatedId;
  const hintId = `${inputId}-hint`;
  const errorId = `${inputId}-error`;
  const describedBy = [hint ? hintId : null, error ? errorId : null].filter(Boolean).join(" ");

  return (
    <div className="grid gap-1.5">
      <label htmlFor={inputId} className="text-sm font-medium">
        {label}
      </label>
      <input
        id={inputId}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy || undefined}
        className={cn(
          "h-11 w-full min-w-0 border border-border-strong bg-bg px-3 text-base text-fg",
          "placeholder:text-fg-muted read-only:bg-surface-raised aria-invalid:border-danger",
          className,
        )}
        {...props}
      />
      {hint ? (
        <p id={hintId} className="text-sm text-pretty text-fg-muted">
          {hint}
        </p>
      ) : null}
      {/* Смонтирован всегда: ошибка озвучивается, даже если фокус уже в поле. */}
      <p
        id={errorId}
        aria-live="polite"
        className={cn("text-sm text-pretty text-danger", !error && "sr-only")}
      >
        {error}
      </p>
    </div>
  );
}
