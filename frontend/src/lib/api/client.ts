import createClient from "openapi-fetch";

import { apiErrorFromException, apiErrorFromResponse } from "./errors";
import type { paths } from "./schema";
import { sessionFetch } from "./profile-session";

/**
 * ходим в API через /api на том же домене, сессия передаётся в cookie
 */
export const apiClient = createClient<paths>({
  baseUrl: "",
  credentials: "include",
  fetch: sessionFetch,
});

type FetchResult<TData> = {
  data?: TData;
  error?: unknown;
  response: Response;
};

/**
 * возвращаем данные ответа, ошибки сети и API приводим к ApiError
 */
export async function unwrap<TData>(request: Promise<FetchResult<TData>>): Promise<TData> {
  let result: FetchResult<TData>;
  try {
    result = await request;
  } catch (cause) {
    throw apiErrorFromException(cause);
  }

  if (!result.response.ok) {
    throw apiErrorFromResponse(result.response, result.error);
  }

  return result.data as TData;
}
