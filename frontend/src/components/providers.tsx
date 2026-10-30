"use client";

import { MotionConfig } from "motion/react";
import type { ReactNode } from "react";

import { TooltipProvider } from "./ui/tooltip";

/** клиентские провайдеры всего приложения. */
export function Providers({ children }: { children: ReactNode }) {
  return (
    <MotionConfig reducedMotion="user">
      <TooltipProvider delayDuration={300}>{children}</TooltipProvider>
    </MotionConfig>
  );
}
