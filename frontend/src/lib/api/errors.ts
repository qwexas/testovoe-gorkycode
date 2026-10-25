import type { ErrorResponse, ServerErrorCode } from "@/types/api";

/** Коды, которые присылает сервер (`{ error: { code, message } }`). */
const SERVER_ERROR_CODES: Record<ServerErrorCode, true> = {
  validation_error: true,
  not_found: true,
  rate_limited: true,
  audio_unsupported: true,
  audio_too_large: true,
  speech_not_recognized: true,
  llm_unavailable: true,
  stt_unavailable: true,
  tts_unavailable: true,
  invalid_recovery_code: true,
  not_implemented: true,
  internal_error: true,
};

/** Коды, которые фронт ставит сам, когда ответа в общем формате нет. */
export type ClientErrorCode = "network_error" | "server_unavailable" | "unexpected_response";

export type ApiErrorCode = ServerErrorCode | ClientErrorCode;

export class ApiError extends Error {
  override readonly name = "ApiError";
  readonly code: ApiErrorCode;
  /** HTTP-статус; `null`, если ответа не было (нет сети). */
  readonly status: number | null;
  /** Секунды из заголовка `Retry-After` (для `rate_limited`). */
  readonly retryAfterSeconds: number | null;

  constructor(options: {
    code: ApiErrorCode;
    message: string;
    status: number | null;
    retryAfterSeconds?: number | null;
    cause?: unknown;
  }) {
    super(options.message, { cause: options.cause });
    this.code = options.code;
    this.status = options.status;
    this.retryAfterSeconds = options.retryAfterSeconds ?? null;
  }
}

const UNAVAILABLE_STATUSES = new Set([500, 502, 503, 504]);

function isServerErrorCode(value: unknown): value is ServerErrorCode {
  return typeof value === "string" && Object.hasOwn(SERVER_ERROR_CODES, value);
}

function isErrorResponse(body: unknown): body is ErrorResponse {
  if (typeof body !== "object" || body === null || !("error" in body)) return false;
  const { error } = body;
  return (
    typeof error === "object" &&
    error !== null &&
    "code" in error &&
    isServerErrorCode(error.code) &&
    "message" in error &&
    typeof error.message === "string"
  );
}

function parseRetryAfter(response: Response): number | null {
  const header = response.headers.get("Retry-After");
  if (!header) return null;
  const seconds = Number(header);
  return Number.isFinite(seconds) && seconds >= 0 ? seconds : null;
}

/** Ответ с ошибкой → ApiError. Тело может быть не в общем формате (502 от nginx, HTML). */
export function apiErrorFromResponse(response: Response, body: unknown): ApiError {
  const retryAfterSeconds = parseRetryAfter(response);

  if (isErrorResponse(body)) {
    return new ApiError({
      code: body.error.code,
      message: body.error.message,
      status: response.status,
      retryAfterSeconds,
    });
  }

  if (UNAVAILABLE_STATUSES.has(response.status)) {
    return new ApiError({
      code: "server_unavailable",
      message: "Сервер не отвечает. Попробуйте ещё раз через минуту.",
      status: response.status,
      retryAfterSeconds,
    });
  }

  return new ApiError({
    code: "unexpected_response",
    message: `Сервер вернул неожиданный ответ (код ${response.status}). Попробуйте ещё раз.`,
    status: response.status,
    retryAfterSeconds,
  });
}

/** Запрос не дошёл до сервера или ответ не разобрался. */
export function apiErrorFromException(cause: unknown): ApiError {
  if (cause instanceof ApiError) return cause;

  if (cause instanceof SyntaxError) {
    return new ApiError({
      code: "unexpected_response",
      message: "Сервер вернул ответ, который не удалось прочитать. Попробуйте ещё раз.",
      status: null,
      cause,
    });
  }

  return new ApiError({
    code: "network_error",
    message: "Нет связи с сервером. Проверьте подключение к интернету и попробуйте ещё раз.",
    status: null,
    cause,
  });
}

export function isApiError(value: unknown): value is ApiError {
  return value instanceof ApiError;
}
