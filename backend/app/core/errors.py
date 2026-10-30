"""ошибки бизнес-логики с кодами из контракта API.

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
    SESSION_REQUIRED = "session_required"
    FORBIDDEN = "forbidden"
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
    """ошибка, которую можно показать пользователю: код из контракта и текст по-русски."""

    code: ClassVar[ErrorCode] = ErrorCode.INTERNAL_ERROR
    default_message: ClassVar[str] = "Что-то пошло не так. Попробуйте ещё раз."

    def __init__(self, message: str | None = None) -> None:
        self.message = message or self.default_message
        super().__init__(self.message)


class SessionRequiredError(DomainError):
    code = ErrorCode.SESSION_REQUIRED
    default_message = "Нет действующей сессии. Создайте профиль или войдите по коду восстановления."


class ForbiddenError(DomainError):
    code = ErrorCode.FORBIDDEN
    default_message = "Создание профиля с этой страницы не разрешено."


class FeatureNotImplementedError(DomainError):
    """возможность объявлена в контракте, но ещё не реализована."""

    code = ErrorCode.NOT_IMPLEMENTED
    default_message = "Эта возможность ещё в разработке и скоро появится."


class InvalidRecoveryCodeError(DomainError):
    """код восстановления не подошёл ни к одному профилю."""

    code = ErrorCode.INVALID_RECOVERY_CODE
    default_message = "Код не подошёл. Проверьте три слова и четыре цифры."


class TooManyAttemptsError(DomainError):
    """превышен лимит попыток; повторить можно через `retry_after_seconds`."""

    code = ErrorCode.RATE_LIMITED
    message_template: ClassVar[str] = "Слишком много попыток. Попробуйте снова через {minutes} мин."

    def __init__(self, retry_after_seconds: int) -> None:
        self.retry_after_seconds = retry_after_seconds
        minutes = max(1, math.ceil(retry_after_seconds / SECONDS_PER_MINUTE))
        super().__init__(self.message_template.format(minutes=minutes))


class TooManyProfilesError(TooManyAttemptsError):
    """С одного адреса создано слишком много профилей."""

    message_template = (
        "С вашего адреса создано слишком много профилей. Попробуйте снова через {minutes} мин."
    )


class TooManyMessagesError(TooManyAttemptsError):
    """профиль отправил слишком много реплик за минуту (`/api/chat` и `/api/voice` вместе)."""

    message_template = "Слишком много запросов. Попробуйте снова через {minutes} мин."


class TooManySpeechRequestsError(TooManyAttemptsError):
    """профиль запросил слишком много озвучек за минуту (`/api/tts`)."""

    message_template = "Слишком много запросов на озвучку. Попробуйте снова через {minutes} мин."


class TooManyCalendarRequestsError(TooManyAttemptsError):
    """С одного адреса слишком часто запрашивают подписку на календарь."""

    message_template = "Слишком много запросов календаря. Попробуйте снова через {minutes} мин."


class AudioUnsupportedError(DomainError):
    """запись в формате, который не распознаётся."""

    code = ErrorCode.AUDIO_UNSUPPORTED
    default_message = "Не получилось прочитать запись. Подойдёт webm, ogg, mp4, wav или mp3."


class AudioTooLargeError(DomainError):
    """запись больше 10 МБ или длиннее 60 секунд."""

    code = ErrorCode.AUDIO_TOO_LARGE
    default_message = "Запись слишком длинная: не больше минуты и 10 МБ."


class SpeechNotRecognizedError(DomainError):
    """В записи не нашлось речи: тишина, шум или неразборчиво."""

    code = ErrorCode.SPEECH_NOT_RECOGNIZED
    default_message = "Не расслышал, повторите, пожалуйста."


class TurnTimeoutError(DomainError):
    """ход не уложился в срок: разбор или распознавание затянулись. Ничего не выполнено."""

    code = ErrorCode.LLM_UNAVAILABLE
    default_message = (
        "Не успел обработать запрос вовремя — ничего не изменено. Повторите, пожалуйста."
    )


class SpeechToTextUnavailableError(DomainError):
    """распознавание речи не работает: модель не загрузилась или упала."""

    code = ErrorCode.STT_UNAVAILABLE
    default_message = "Распознавание речи сейчас недоступно. Напишите, пожалуйста, текстом."


class TextToSpeechUnavailableError(DomainError):
    """озвучка не работает: модель не загрузилась или упала."""

    code = ErrorCode.TTS_UNAVAILABLE
    default_message = "Озвучка сейчас недоступна, ответ можно прочитать."


class UnknownVoiceError(DomainError):
    """запрошен голос, которого нет у синтезатора речи."""

    code = ErrorCode.VALIDATION_ERROR
    default_message = "Такого голоса нет."


class CalendarNotFoundError(DomainError):
    """по ссылке подписки нет календаря: токен неверный или профиль удалён."""

    code = ErrorCode.NOT_FOUND
    default_message = "Календарь не найден. Возьмите новую ссылку в настройках профиля."


class UndoUnavailableError(DomainError):
    """действие нельзя отменить: окно отмены прошло, действие уже отменено или чужое."""

    code = ErrorCode.NOT_FOUND
    default_message = "Отменить уже нельзя."


class EventValidationError(DomainError):
    """поля записи противоречат правилам (например, встреча без времени)."""

    code = ErrorCode.VALIDATION_ERROR
    default_message = "Проверьте данные записи."


class EventNotFoundError(DomainError):
    """записи нет в профиле — или она принадлежит другому профилю."""

    code = ErrorCode.NOT_FOUND
    default_message = "Запись не найдена."
