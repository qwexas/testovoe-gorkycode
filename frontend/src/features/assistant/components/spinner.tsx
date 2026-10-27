"use client";

import { useReducedMotion } from "motion/react";
import { useEffect, useState } from "react";

import { tty } from "@/components/ui/tty";

const FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏";

/** Брайлевский спиннер, как в терминале. При reduced motion — неподвижный кадр. */
export function Spinner() {
  const reduced = useReducedMotion() ?? false;
  const [frame, setFrame] = useState(0);
  useEffect(() => {
    if (reduced) return undefined;
    const interval = window.setInterval(() => setFrame((value) => value + 1), 80);
    return () => window.clearInterval(interval);
  }, [reduced]);
  return (
    <span aria-hidden="true" className={tty.accent}>
      {FRAMES[frame % FRAMES.length]}
    </span>
  );
}
