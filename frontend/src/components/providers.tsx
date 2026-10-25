"use client";

import { MotionConfig } from "motion/react";
import type { ReactNode } from "react";

import { TooltipProvider } from "./ui/tooltip";

/** Клиентские провайдеры всего приложения. */
export function Providers({ children }: { children: ReactNode }) {
  return (
    <MotionConfig reducedMotion="user">
      <TooltipProvider delayDuration={300}>{children}</TooltipProvider>
    </MotionConfig>
  );
}
