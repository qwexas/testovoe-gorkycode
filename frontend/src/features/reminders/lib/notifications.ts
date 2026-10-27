/**
 * Уведомления браузера для напоминаний (решение Q32, вариант «б»): работают, пока вкладка
 * открыта, без Web Push и service worker. Разрешение спрашиваем только по нажатию кнопки.
 */

export type NotificationState = "unsupported" | NotificationPermission;

export function notificationState(): NotificationState {
  if (typeof window === "undefined" || typeof Notification === "undefined") return "unsupported";
  return Notification.permission;
}

/** Вызывать из обработчика нажатия: Safari спрашивает разрешение только по жесту. */
export async function requestNotifications(): Promise<NotificationState> {
  if (typeof Notification === "undefined") return "unsupported";
  try {
    return await Notification.requestPermission();
  } catch {
    return Notification.permission;
  }
}

/**
 * Показывает уведомление. Chrome на Android без service worker бросает TypeError —
 * тогда остаются звук и строка в сессии; возвращает, получилось ли.
 */
export function showNotification(title: string, body: string, tag: string): boolean {
  if (notificationState() !== "granted") return false;
  try {
    const notification = new Notification(title, { body, tag, lang: "ru" });
    notification.onclick = () => {
      window.focus();
      notification.close();
    };
    return true;
  } catch {
    return false;
  }
}
