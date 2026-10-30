"use client";

import { useCallback, useRef, useState } from "react";

import { type ApiError, apiErrorFromException } from "@/lib/api/errors";

/**
 * храним ошибку и pending для формы, повторный запуск до конца запроса пропускаем
 */
export function useAsyncAction<TArgs extends unknown[]>(
  action: (...args: TArgs) => Promise<void>,
): {
  run: (...args: TArgs) => Promise<boolean>;
  pending: boolean;
  error: ApiError | null;
} {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const running = useRef(false);

  const run = useCallback(
    async (...args: TArgs) => {
      if (running.current) return false;
      running.current = true;
      setPending(true);
      setError(null);
      try {
        await action(...args);
        return true;
      } catch (cause) {
        setError(apiErrorFromException(cause));
        return false;
      } finally {
        running.current = false;
        setPending(false);
      }
    },
    [action],
  );

  return { run, pending, error };
}
