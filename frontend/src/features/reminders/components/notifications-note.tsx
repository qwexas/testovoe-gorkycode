"use client";

import { tty } from "@/components/ui/tty";
import { cn } from "@/lib/cn";

import { useNotificationState } from "../hooks/use-notification-state";

/**
 * Как сработают напоминания: строка под планом дня и кнопка, которая спрашивает
 * разрешение на уведомления (только по нажатию, не при загрузке).
 */
export function NotificationsNote() {
  const { state, request } = useNotificationState();

  return (
    <div className="grid justify-items-start gap-1 px-3 text-xs">
      <p className={cn(tty.muted, "text-pretty")}>
        {state === "granted"
          ? "Напомню уведомлением, сигналом и строкой в сессии, пока вкладка открыта."
          : state === "denied"
            ? "Уведомления запрещены в настройках браузера — напомню сигналом и строкой в сессии, пока вкладка открыта."
            : state === "unsupported"
              ? "Напомню сигналом и строкой в сессии, пока вкладка открыта."
              : "Напомню сигналом и строкой в сессии, пока вкладка открыта. Уведомления браузера — по кнопке."}
      </p>
      {state === "default" ? (
        <button type="button" onClick={() => void request()} className={cn(tty.btn, "-ml-1.5")}>
          включить уведомления
        </button>
      ) : null}
      <p className={cn(tty.muted, "text-pretty")}>
        Чтобы напоминания приходили и с закрытой вкладкой, подпишитесь на календарь в меню профиля.
      </p>
    </div>
  );
}
