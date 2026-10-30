"use client";

import { useId } from "react";

import { useTheme } from "@/hooks/use-theme";
import { THEME_PREFERENCES, type ThemePreference } from "@/lib/theme";

const LABELS: Record<ThemePreference, string> = {
  system: "авто",
  light: "светлая",
  dark: "тёмная",
};

/**
 * выбор темы радиокнопками: видно все три варианта сразу, стрелки переключают
 * (нативное поведение radio). Внешний вид задаёт место, где стоит выбор.
 */
export function ThemeChoice({
  className,
  legendClassName,
  optionClassName,
  legend = "Тема",
}: {
  className?: string;
  legendClassName?: string;
  /** классы подписи; выбранная получает data-checked. */
  optionClassName?: string;
  legend?: string;
}) {
  const { preference, setPreference } = useTheme();
  const name = useId();

  return (
    <fieldset className={className}>
      <legend className={legendClassName}>{legend}</legend>
      {THEME_PREFERENCES.map((value) => (
        <label
          key={value}
          className={optionClassName}
          data-checked={preference === value || undefined}
          title={value === "system" ? "Как в системе" : undefined}
        >
          <input
            type="radio"
            name={name}
            value={value}
            checked={preference === value}
            onChange={() => setPreference(value)}
            className="sr-only"
          />
          {LABELS[value]}
        </label>
      ))}
    </fieldset>
  );
}
