import createClient from "openapi-fetch";

import { apiErrorFromException, apiErrorFromResponse } from "./errors";
import type { paths } from "./schema";
import { sessionFetch } from "./profile-session";

/**
 * Типизированный клиент API. Фронт и API на одном домене (`/api` → FastAPI),
 * поэтому baseUrl пустой, а профиль едет в first-party cookie.
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
 * Ждёт ответ openapi-fetch и возвращает данные успешного ответа.
 * Любая неудача (нет сети, 4xx/5xx, не-JSON) превращается в ApiError.
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
