"use client";

import { useCallback, useSyncExternalStore } from "react";

import {
  type NotificationState,
  notificationState,
  requestNotifications,
} from "../lib/notifications";

const listeners = new Set<() => void>();

function notify(): void {
  for (const listener of listeners) listener();
}

function subscribe(onChange: () => void): () => void {
  listeners.add(onChange);
  // разрешение могут поменять в настройках сайта, не перезагружая страницу.
  let status: PermissionStatus | null = null;
  let disposed = false;
  void navigator.permissions
    ?.query({ name: "notifications" })
    .then((result) => {
      if (disposed) return;
      status = result;
      status.addEventListener("change", onChange);
    })
    .catch(() => undefined);
  return () => {
    disposed = true;
    listeners.delete(onChange);
    status?.removeEventListener("change", onChange);
  };
}

function getServerSnapshot(): NotificationState {
  return "unsupported";
}

/** состояние разрешения на уведомления и запрос разрешения по нажатию. */
export function useNotificationState(): {
  state: NotificationState;
  request: () => Promise<NotificationState>;
} {
  const state = useSyncExternalStore(subscribe, notificationState, getServerSnapshot);
  const request = useCallback(async () => {
    const next = await requestNotifications();
    notify();
    return next;
  }, []);
  return { state, request };
}
