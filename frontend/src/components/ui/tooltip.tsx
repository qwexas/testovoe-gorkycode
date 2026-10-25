"use client";

import * as RadixTooltip from "@radix-ui/react-tooltip";
import type { ReactNode } from "react";

export const TooltipProvider = RadixTooltip.Provider;

/**
 * Подсказка при наведении и фокусе с клавиатуры. Только для дополнительной информации:
 * на тач-экранах её не видно, поэтому важное должно быть в самом элементе.
 */
export function Tooltip({
  content,
  children,
  side = "bottom",
}: {
  content: ReactNode;
  children: ReactNode;
  side?: "top" | "right" | "bottom" | "left";
}) {
  return (
    <RadixTooltip.Root>
      <RadixTooltip.Trigger asChild>{children}</RadixTooltip.Trigger>
      <RadixTooltip.Portal>
        <RadixTooltip.Content
          side={side}
          sideOffset={6}
          collisionPadding={16}
          className="z-50 max-w-xs rounded-lg border border-border bg-surface-raised px-3 py-2 text-xs leading-relaxed text-fg shadow-lg"
        >
          {content}
        </RadixTooltip.Content>
      </RadixTooltip.Portal>
    </RadixTooltip.Root>
  );
}
