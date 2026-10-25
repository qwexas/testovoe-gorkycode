"use client";

import type { ReactElement } from "react";

import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useTheme } from "@/hooks/use-theme";
import { isThemePreference } from "@/lib/theme";

import { ANSWER_SOUND_LABEL } from "../model/copy";

/**
 * Настройки для узких экранов: тема и озвучка в одном меню (паттерн APG «меню»).
 * Кнопку-триггер рисует вариант, чтобы она была в его стиле.
 */
export function SettingsMenu({
  trigger,
  soundOn,
  onSoundChange,
}: {
  trigger: ReactElement;
  soundOn: boolean;
  onSoundChange: (value: boolean) => void;
}) {
  const { preference, setPreference } = useTheme();

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>{trigger}</DropdownMenuTrigger>
      <DropdownMenuContent className="min-w-56 font-sans">
        <DropdownMenuLabel className="text-fg-muted">Тема оформления</DropdownMenuLabel>
        <DropdownMenuRadioGroup
          value={preference}
          onValueChange={(value) => {
            if (isThemePreference(value)) setPreference(value);
          }}
        >
          <DropdownMenuRadioItem value="system">Как в системе</DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="light">Светлая</DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="dark">Тёмная</DropdownMenuRadioItem>
        </DropdownMenuRadioGroup>
        <DropdownMenuSeparator />
        <DropdownMenuCheckboxItem
          checked={soundOn}
          onCheckedChange={(value) => onSoundChange(value === true)}
        >
          {ANSWER_SOUND_LABEL}
        </DropdownMenuCheckboxItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
