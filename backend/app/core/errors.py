"""Ошибки бизнес-логики с кодами из контракта API.

Слой `core` не знает про HTTP: здесь только код ошибки и сообщение для пользователя.
HTTP-статус по коду выбирает слой `api`.
"""

import math
from enum import StrEnum
from typing import ClassVar

SECONDS_PER_MINUTE = 60


class ErrorCode(StrEnum):
    """Коды ошибок из контракта API."""

    VALIDATION_ERROR = "validation_error"
    NOT_FOUND = "not_found"
    RATE_LIMITED = "rate_limited"
    AUDIO_UNSUPPORTED = "audio_unsupported"
    AUDIO_TOO_LARGE = "audio_too_large"
    SPEECH_NOT_RECOGNIZED = "speech_not_recognized"
    LLM_UNAVAILABLE = "llm_unavailable"
    STT_UNAVAILABLE = "stt_unavailable"
    TTS_UNAVAILABLE = "tts_unavailable"
    INVALID_RECOVERY_CODE = "invalid_recovery_code"
    NOT_IMPLEMENTED = "not_implemented"
    INTERNAL_ERROR = "internal_error"


class DomainError(Exception):
    """Ошибка, которую можно показать пользователю: код из контракта и текст по-русски."""

    code: ClassVar[ErrorCode] = ErrorCode.INTERNAL_ERROR
    default_message: ClassVar[str] = "Что-то пошло не так. Попробуйте ещё раз."

    def __init__(self, message: str | None = None) -> None:
        self.message = message or self.default_message
        super().__init__(self.message)


class FeatureNotImplementedError(DomainError):
    """Возможность объявлена в контракте, но ещё не реализована."""

    code = ErrorCode.NOT_IMPLEMENTED
    default_message = "Эта возможность ещё в разработке и скоро появится."


class InvalidRecoveryCodeError(DomainError):
    """Код восстановления не подошёл ни к одному профилю."""

    code = ErrorCode.INVALID_RECOVERY_CODE
    default_message = "Код не подошёл. Проверьте три слова и четыре цифры."


class TooManyAttemptsError(DomainError):
    """Превышен лимит попыток; повторить можно через `retry_after_seconds`."""

    code = ErrorCode.RATE_LIMITED

    def __init__(self, retry_after_seconds: int) -> None:
        self.retry_after_seconds = retry_after_seconds
        minutes = max(1, math.ceil(retry_after_seconds / SECONDS_PER_MINUTE))
        super().__init__(f"Слишком много попыток. Попробуйте снова через {minutes} мин.")
