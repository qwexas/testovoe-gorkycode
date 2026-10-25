"use client";

import { useCallback, useState } from "react";

import { type ApiError, apiErrorFromException } from "@/lib/api/errors";

/**
 * Состояние одного асинхронного действия из UI (кнопка, форма в окне):
 * идёт ли запрос и чем он закончился. Возвращает true при успехе.
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

  const run = useCallback(
    async (...args: TArgs) => {
      setPending(true);
      setError(null);
      try {
        await action(...args);
        return true;
      } catch (cause) {
        setError(apiErrorFromException(cause));
        return false;
      } finally {
        setPending(false);
      }
    },
    [action],
  );

  return { run, pending, error };
}
