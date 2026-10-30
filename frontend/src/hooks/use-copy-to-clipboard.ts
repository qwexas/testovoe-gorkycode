"use client";

import { useCallback, useEffect, useRef, useState } from "react";

export type CopyStatus = "idle" | "copied" | "failed";

const RESET_AFTER_MS = 2500;

/**
 * копирование в буфер обмена. Clipboard API есть только в безопасном контексте
 * (HTTPS или localhost), поэтому неудача — штатный исход, а не исключение.
 */
export function useCopyToClipboard(): {
  status: CopyStatus;
  copy: (text: string) => Promise<boolean>;
} {
  const [status, setStatus] = useState<CopyStatus>("idle");
  const resetTimer = useRef<number | undefined>(undefined);

  useEffect(() => () => window.clearTimeout(resetTimer.current), []);

  const copy = useCallback(async (text: string) => {
    window.clearTimeout(resetTimer.current);
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      setStatus("failed");
      return false;
    }
    setStatus("copied");
    resetTimer.current = window.setTimeout(() => setStatus("idle"), RESET_AFTER_MS);
    return true;
  }, []);

  return { status, copy };
}
