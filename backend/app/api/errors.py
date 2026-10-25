"""Перевод ошибок в единый формат `{"error": {"code", "message"}}` и их описание в OpenAPI."""

from collections.abc import Mapping
from http import HTTPStatus
from types import MappingProxyType
from typing import Any, Final

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from app.api.schemas.errors import ErrorBody, ErrorResponse
from app.core.errors import DomainError, ErrorCode, TooManyAttemptsError

ERROR_STATUS: Final[Mapping[ErrorCode, HTTPStatus]] = MappingProxyType(
    {
        ErrorCode.VALIDATION_ERROR: HTTPStatus.UNPROCESSABLE_ENTITY,
        ErrorCode.NOT_FOUND: HTTPStatus.NOT_FOUND,
        ErrorCode.RATE_LIMITED: HTTPStatus.TOO_MANY_REQUESTS,
        ErrorCode.AUDIO_UNSUPPORTED: HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
        ErrorCode.AUDIO_TOO_LARGE: HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
        ErrorCode.SPEECH_NOT_RECOGNIZED: HTTPStatus.UNPROCESSABLE_ENTITY,
        ErrorCode.LLM_UNAVAILABLE: HTTPStatus.SERVICE_UNAVAILABLE,
        ErrorCode.STT_UNAVAILABLE: HTTPStatus.SERVICE_UNAVAILABLE,
        ErrorCode.TTS_UNAVAILABLE: HTTPStatus.SERVICE_UNAVAILABLE,
        ErrorCode.INVALID_RECOVERY_CODE: HTTPStatus.BAD_REQUEST,
        ErrorCode.NOT_IMPLEMENTED: HTTPStatus.NOT_IMPLEMENTED,
        ErrorCode.INTERNAL_ERROR: HTTPStatus.INTERNAL_SERVER_ERROR,
    }
)

VALIDATION_MESSAGE = "Проверьте данные запроса."
INTERNAL_ERROR_MESSAGE = "Что-то пошло не так на сервере. Попробуйте ещё раз."

_HTTP_ERRORS: Final[Mapping[int, tuple[ErrorCode, str]]] = MappingProxyType(
    {
        HTTPStatus.NOT_FOUND: (ErrorCode.NOT_FOUND, "Не найдено."),
        HTTPStatus.METHOD_NOT_ALLOWED: (
            ErrorCode.VALIDATION_ERROR,
            "Такой запрос здесь не поддерживается.",
        ),
    }
)


def error_response(
    code: ErrorCode, message: str, headers: Mapping[str, str] | None = None
) -> JSONResponse:
    """JSON-ответ с ошибкой и HTTP-статусом, соответствующим коду."""
    return _render_error(ERROR_STATUS[code], code, message, headers)


def error_responses(*codes: ErrorCode) -> dict[int | str, dict[str, Any]]:
    """Описание ответов-ошибок для параметра `responses` маршрута (OpenAPI)."""
    codes_by_status: dict[HTTPStatus, list[ErrorCode]] = {}
    for code in codes:
        codes_by_status.setdefault(ERROR_STATUS[code], []).append(code)
    return {
        int(status): {
            "model": ErrorResponse,
            "description": ", ".join(f"`{code}`" for code in status_codes),
        }
        for status, status_codes in codes_by_status.items()
    }


def install_error_handlers(app: FastAPI) -> None:
    """Подключает обработчики, которые отдают все ошибки в едином формате."""
    app.exception_handler(DomainError)(_handle_domain_error)
    app.exception_handler(RequestValidationError)(_handle_validation_error)
    app.exception_handler(HTTPException)(_handle_http_exception)
    app.exception_handler(Exception)(_handle_unexpected_error)


def _render_error(
    status_code: int, code: ErrorCode, message: str, headers: Mapping[str, str] | None = None
) -> JSONResponse:
    body = ErrorResponse(error=ErrorBody(code=code, message=message))
    return JSONResponse(
        status_code=status_code, content=body.model_dump(mode="json"), headers=headers
    )


async def _handle_domain_error(_: Request, exc: DomainError) -> JSONResponse:
    headers = _retry_after_header(exc) if isinstance(exc, TooManyAttemptsError) else None
    return error_response(exc.code, exc.message, headers)


def _retry_after_header(exc: TooManyAttemptsError) -> dict[str, str]:
    return {"Retry-After": str(exc.retry_after_seconds)}


async def _handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    return error_response(ErrorCode.VALIDATION_ERROR, _describe_validation_error(exc))


def _describe_validation_error(exc: RequestValidationError) -> str:
    field_names = [
        error["loc"][-1]
        for error in exc.errors()
        if error.get("loc") and isinstance(error["loc"][-1], str)
    ]
    if not field_names:
        return VALIDATION_MESSAGE
    return f"{VALIDATION_MESSAGE} Поле: «{field_names[0]}»."


async def _handle_http_exception(_: Request, exc: HTTPException) -> JSONResponse:
    if exc.status_code >= HTTPStatus.INTERNAL_SERVER_ERROR:
        return error_response(ErrorCode.INTERNAL_ERROR, INTERNAL_ERROR_MESSAGE)
    code, message = _HTTP_ERRORS.get(
        exc.status_code, (ErrorCode.VALIDATION_ERROR, VALIDATION_MESSAGE)
    )
    return _render_error(exc.status_code, code, message, exc.headers)


async def _handle_unexpected_error(_: Request, __: Exception) -> JSONResponse:
    # Трассировку пишет сервер: Starlette пробрасывает исключение дальше после ответа.
    return error_response(ErrorCode.INTERNAL_ERROR, INTERNAL_ERROR_MESSAGE)
