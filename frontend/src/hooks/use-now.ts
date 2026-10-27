"use client";

import { useSyncExternalStore } from "react";

/*
 * Общие часы интерфейса: одно значение «сейчас» на всю страницу, тикает на границе
 * каждой минуты (время в интерфейсе — с точностью до минуты, напоминания — тоже).
 * Пока подписчиков нет, таймер не работает.
 */

const MINUTE_MS = 60_000;

let current = 0;
let timer: number | undefined;
const listeners = new Set<() => void>();

function emit(): void {
  current = Date.now();
  for (const listener of listeners) listener();
}

function schedule(): void {
  window.clearTimeout(timer);
  // +50 мс: срабатываем гарантированно после смены минуты.
  const delay = MINUTE_MS - (Date.now() % MINUTE_MS) + 50;
  timer = window.setTimeout(() => {
    emit();
    schedule();
  }, delay);
}

/** Фоновые вкладки тормозят таймеры: при возвращении сразу сверяем часы. */
function onVisibility(): void {
  if (document.visibilityState !== "visible") return;
  emit();
  schedule();
}

function subscribe(onChange: () => void): () => void {
  listeners.add(onChange);
  if (listeners.size === 1) {
    schedule();
    document.addEventListener("visibilitychange", onVisibility);
  }
  return () => {
    listeners.delete(onChange);
    if (listeners.size === 0) {
      window.clearTimeout(timer);
      document.removeEventListener("visibilitychange", onVisibility);
    }
  };
}

function getSnapshot(): number {
  if (current === 0) current = Date.now();
  return current;
}

function getServerSnapshot(): null {
  return null;
}

/**
 * Текущий момент с точностью до минуты. На сервере и при гидрации — null: время зависит
 * от момента открытия страницы, а не от момента сборки.
 */
export function useNow(): Date | null {
  const value = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
  return value === null ? null : new Date(value);
}
