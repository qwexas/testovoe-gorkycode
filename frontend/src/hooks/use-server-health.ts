"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { type ApiError, apiErrorFromException } from "@/lib/api/errors";
import { fetchHealth } from "@/lib/api/health";
import type { HealthResponse } from "@/types/api";

export type ServerHealth =
  | { status: "checking" }
  | { status: "online"; health: HealthResponse }
  | { status: "degraded"; health: HealthResponse }
  | { status: "offline"; error: ApiError };

const POLL_INTERVAL_MS = 30_000;

function toServerHealth(health: HealthResponse): ServerHealth {
  const hasFailure = Object.values(health.checks).some((check) => check === "fail");
  return hasFailure ? { status: "degraded", health } : { status: "online", health };
}

/**
 * статус сервера по GET /api/health: при открытии, раз в 30 с, пока вкладка видима,
 * при возврате на вкладку и при восстановлении сети.
 */
export function useServerHealth(): {
  health: ServerHealth;
  isChecking: boolean;
  recheck: () => void;
} {
  const [health, setHealth] = useState<ServerHealth>({ status: "checking" });
  const [isChecking, setIsChecking] = useState(true);
  const checkRef = useRef<() => Promise<void>>(async () => {});

  useEffect(() => {
    let controller: AbortController | null = null;

    const check = async () => {
      controller?.abort();
      const current = new AbortController();
      controller = current;
      let next: ServerHealth;
      try {
        next = toServerHealth(await fetchHealth(current.signal));
      } catch (error) {
        next = { status: "offline", error: apiErrorFromException(error) };
      }
      if (current.signal.aborted) return;
      setHealth(next);
      setIsChecking(false);
    };

    const checkIfVisible = () => {
      if (document.visibilityState === "visible") void check();
    };

    checkRef.current = check;
    void check();
    const interval = window.setInterval(checkIfVisible, POLL_INTERVAL_MS);
    document.addEventListener("visibilitychange", checkIfVisible);
    window.addEventListener("online", checkIfVisible);

    return () => {
      controller?.abort();
      window.clearInterval(interval);
      document.removeEventListener("visibilitychange", checkIfVisible);
      window.removeEventListener("online", checkIfVisible);
    };
  }, []);

  const recheck = useCallback(() => {
    setIsChecking(true);
    void checkRef.current();
  }, []);

  return { health, isChecking, recheck };
}
