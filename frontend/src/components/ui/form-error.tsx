import { cn } from "@/lib/cn";

/**
 * Ошибка действия, не привязанная к полю. Регион смонтирован всегда (пустой),
 * чтобы экранный диктор надёжно озвучил появившийся текст.
 */
export function FormError({ message, className }: { message: string | null; className?: string }) {
  return (
    <p
      role="alert"
      className={cn("text-sm text-pretty text-danger", message ? "mt-4" : "sr-only", className)}
    >
      {message}
    </p>
  );
}
