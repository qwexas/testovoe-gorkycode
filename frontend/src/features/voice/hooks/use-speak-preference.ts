"use client";

import { useCallback, useSyncExternalStore } from "react";

/*
 * Переключатель «Озвучивать ответы» (решение Q26: ответ озвучивается автоматически,
 * звук можно выключить). Выбор хранится в localStorage; если хранилище недоступно
 * (приватный режим), живёт в памяти до перезагрузки.
 */

const STORAGE_KEY = "gorky-speak-replies";
const DEFAULT_ON = true;

let cached: boolean | null = null;
const listeners = new Set<() => void>();

function read(): boolean {
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    return stored === null ? DEFAULT_ON : stored === "on";
  } catch {
    return DEFAULT_ON;
  }
}

function write(value: boolean): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, value ? "on" : "off");
  } catch {
    // Хранилище недоступно — выбор действует до перезагрузки.
  }
}

function subscribe(onChange: () => void): () => void {
  listeners.add(onChange);
  const onStorage = (event: StorageEvent) => {
    if (event.key !== null && event.key !== STORAGE_KEY) return;
    cached = read();
    onChange();
  };
  window.addEventListener("storage", onStorage);
  return () => {
    listeners.delete(onChange);
    window.removeEventListener("storage", onStorage);
  };
}

function getSnapshot(): boolean {
  cached ??= read();
  return cached;
}

function getServerSnapshot(): boolean {
  return DEFAULT_ON;
}

export function useSpeakPreference(): [boolean, (value: boolean) => void] {
  const value = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
  const setValue = useCallback((next: boolean) => {
    cached = next;
    write(next);
    for (const listener of listeners) listener();
  }, []);
  return [value, setValue];
}
