"use client";

import type { ComponentType } from "react";

import { useTheme } from "@/hooks/use-theme";
import { type ThemePreference, isThemePreference } from "@/lib/theme";

import { Button } from "./ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from "./ui/dropdown-menu";
import { MonitorIcon, MoonIcon, SunIcon } from "./ui/icons";
import { Tooltip } from "./ui/tooltip";

const THEME_OPTIONS: Record<
  ThemePreference,
  { label: string; Icon: ComponentType<{ size?: number }> }
> = {
  system: { label: "Как в системе", Icon: MonitorIcon },
  light: { label: "Светлая", Icon: SunIcon },
  dark: { label: "Тёмная", Icon: MoonIcon },
};

export function ThemeSwitcher() {
  const { preference, setPreference } = useTheme();
  const current = THEME_OPTIONS[preference];

  return (
    <DropdownMenu>
      <Tooltip content="Тема оформления">
        <DropdownMenuTrigger asChild>
          <Button
            variant="ghost"
            size="icon"
            aria-label={`Тема оформления: ${current.label.toLowerCase()}`}
          >
            <current.Icon size={20} />
          </Button>
        </DropdownMenuTrigger>
      </Tooltip>
      <DropdownMenuContent className="min-w-52">
        <DropdownMenuLabel className="text-fg-muted">Тема оформления</DropdownMenuLabel>
        <DropdownMenuRadioGroup
          value={preference}
          onValueChange={(value) => {
            if (isThemePreference(value)) setPreference(value);
          }}
        >
          {Object.entries(THEME_OPTIONS).map(([value, { label, Icon }]) => (
            <DropdownMenuRadioItem key={value} value={value}>
              <Icon />
              {label}
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
