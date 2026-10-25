"use client";

import { useCallback, useLayoutEffect, useSyncExternalStore } from "react";

import {
  DEFAULT_THEME_PREFERENCE,
  applyTheme,
  readThemePreference,
  resolveTheme,
  subscribeToThemeSources,
  writeThemePreference,
  type ThemePreference,
} from "@/lib/theme";

// Внешнее хранилище выбора темы. Кэш в памяти нужен, когда localStorage недоступен:
// выбор тогда действует до перезагрузки страницы.
let cachedPreference: ThemePreference | null = null;
const listeners = new Set<() => void>();

function getPreference(): ThemePreference {
  cachedPreference ??= readThemePreference();
  return cachedPreference;
}

function getServerPreference(): ThemePreference {
  return DEFAULT_THEME_PREFERENCE;
}

function syncDocumentTheme(): void {
  applyTheme(resolveTheme(getPreference()));
}

function subscribe(onChange: () => void): () => void {
  listeners.add(onChange);
  return () => listeners.delete(onChange);
}

function notify(): void {
  for (const listener of listeners) listener();
}

export function useTheme(): {
  preference: ThemePreference;
  setPreference: (preference: ThemePreference) => void;
} {
  const preference = useSyncExternalStore(subscribe, getPreference, getServerPreference);

  useLayoutEffect(() => {
    // Тему до гидрации ставит инлайн-скрипт; здесь повторяем на случай, если React
    // сбросил атрибуты <html> (перемонтирование в Strict Mode в dev).
    syncDocumentTheme();
    return subscribeToThemeSources(() => {
      cachedPreference = readThemePreference();
      syncDocumentTheme();
      notify();
    });
  }, []);

  const setPreference = useCallback((next: ThemePreference) => {
    cachedPreference = next;
    writeThemePreference(next);
    syncDocumentTheme();
    notify();
  }, []);

  return { preference, setPreference };
}
