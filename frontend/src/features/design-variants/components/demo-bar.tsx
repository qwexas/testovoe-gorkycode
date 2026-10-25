"use client";

import Link from "next/link";
import { useId } from "react";

import { cn } from "@/lib/cn";

import { DEMO_STATES } from "../model/states";
import { type DemoStateId, isDemoStateId } from "../model/types";

export const VARIANTS = [
  { id: 1, name: "Консоль" },
  { id: 2, name: "Рукопись" },
  { id: 3, name: "Шар" },
] as const;

export type VariantId = (typeof VARIANTS)[number]["id"];

/**
 * Служебная панель демо: переход между вариантами и готовыми состояниями.
 * Нарочно нейтральная (общие токены проекта), чтобы не смешиваться с дизайном варианта.
 * Скрывается параметром `?bar=0` — для скриншотов.
 */
export function DemoBar({
  variant,
  current,
  onJump,
}: {
  variant: VariantId;
  current: DemoStateId | null;
  onJump: (id: DemoStateId) => void;
}) {
  const selectId = useId();

  return (
    <nav
      aria-label="Демо: варианты и состояния"
      className="flex shrink-0 items-center gap-x-3 gap-y-2 border-b border-border bg-surface px-4 py-2 font-sans text-sm text-fg"
    >
      <Link
        href="/variants"
        className="font-medium text-accent-text underline-offset-4 hover:underline max-sm:hidden"
      >
        Варианты дизайна
      </Link>
      <ul className="flex items-center gap-1">
        {VARIANTS.map(({ id, name }) => (
          <li key={id}>
            <Link
              href={`/variants/${id}${current ? `?state=${current}` : ""}`}
              aria-current={id === variant ? "page" : undefined}
              className={cn(
                "inline-flex h-8 items-center rounded-md px-2.5 transition-colors",
                id === variant
                  ? "bg-accent-fill text-on-accent"
                  : "text-fg-muted hover:bg-surface-raised hover:text-fg",
              )}
            >
              {id}.<span className="max-sm:sr-only"> {name}</span>
            </Link>
          </li>
        ))}
      </ul>
      <div className="ml-auto flex min-w-0 items-center gap-2">
        <label htmlFor={selectId} className="text-fg-muted max-sm:sr-only">
          Состояние
        </label>
        <select
          id={selectId}
          value={current ?? ""}
          onChange={(event) => {
            const { value } = event.target;
            if (!isDemoStateId(value)) return;
            onJump(value);
            const url = new URL(window.location.href);
            url.searchParams.set("state", value);
            window.history.replaceState(null, "", url);
          }}
          className="h-9 min-w-0 rounded-md border border-border-strong bg-bg px-2 text-base text-fg max-sm:w-full sm:text-sm"
        >
          {current === null ? <option value="">Свой сценарий</option> : null}
          {DEMO_STATES.map(({ id, label }) => (
            <option key={id} value={id}>
              {label}
            </option>
          ))}
        </select>
      </div>
    </nav>
  );
}
