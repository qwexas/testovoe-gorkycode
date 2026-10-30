/**
 * тема интерфейса (решение Q36): светлая / тёмная / системная, по умолчанию системная.
 * Выбор хранится в localStorage; тема применяется атрибутом data-theme на <html>.
 */

export const THEME_PREFERENCES = ["system", "light", "dark"] as const;

export type ThemePreference = (typeof THEME_PREFERENCES)[number];
export type ResolvedTheme = Exclude<ThemePreference, "system">;

export const DEFAULT_THEME_PREFERENCE: ThemePreference = "system";

const STORAGE_KEY = "gorky-theme";
const DARK_QUERY = "(prefers-color-scheme: dark)";

export function isThemePreference(value: unknown): value is ThemePreference {
  return typeof value === "string" && (THEME_PREFERENCES as readonly string[]).includes(value);
}

export function readThemePreference(): ThemePreference {
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    return isThemePreference(stored) ? stored : DEFAULT_THEME_PREFERENCE;
  } catch {
    return DEFAULT_THEME_PREFERENCE;
  }
}

export function writeThemePreference(preference: ThemePreference): void {
  try {
    if (preference === DEFAULT_THEME_PREFERENCE) {
      window.localStorage.removeItem(STORAGE_KEY);
    } else {
      window.localStorage.setItem(STORAGE_KEY, preference);
    }
  } catch {
    // Хранилище недоступно (приватный режим, запрет cookies): тема живёт до перезагрузки.
  }
}

export function systemPrefersDark(): boolean {
  return window.matchMedia(DARK_QUERY).matches;
}

export function resolveTheme(preference: ThemePreference): ResolvedTheme {
  if (preference !== "system") return preference;
  return systemPrefersDark() ? "dark" : "light";
}

export function applyTheme(theme: ResolvedTheme): void {
  const root = document.documentElement;
  if (root.dataset.theme === theme) return;
  // на время смены темы гасим переходы цвета, иначе все кнопки «перетекают» разом.
  const freeze = document.createElement("style");
  freeze.textContent = "*,*::before,*::after{transition:none!important}";
  document.head.append(freeze);
  root.dataset.theme = theme;
  root.style.colorScheme = theme;
  void window.getComputedStyle(root).opacity;
  requestAnimationFrame(() => freeze.remove());
}

/** подписка на смену системной темы и на выбор темы в другой вкладке. */
export function subscribeToThemeSources(onChange: () => void): () => void {
  const media = window.matchMedia(DARK_QUERY);
  const onStorage = (event: StorageEvent) => {
    if (event.key === null || event.key === STORAGE_KEY) onChange();
  };
  media.addEventListener("change", onChange);
  window.addEventListener("storage", onStorage);
  return () => {
    media.removeEventListener("change", onChange);
    window.removeEventListener("storage", onStorage);
  };
}

/**
 * инлайн-скрипт для <head>: ставит data-theme до первой отрисовки, чтобы не было
 * вспышки неверной темы. Повторяет readThemePreference + resolveTheme + applyTheme.
 */
export const themeInitScript = `(function(){var d=document.documentElement,p=${JSON.stringify(
  DEFAULT_THEME_PREFERENCE,
)};try{var s=localStorage.getItem(${JSON.stringify(
  STORAGE_KEY,
)});if(s==="light"||s==="dark"||s==="system")p=s}catch(e){}var t=p==="system"?(window.matchMedia(${JSON.stringify(
  DARK_QUERY,
)}).matches?"dark":"light"):p;d.setAttribute("data-theme",t);d.style.colorScheme=t})()`;
