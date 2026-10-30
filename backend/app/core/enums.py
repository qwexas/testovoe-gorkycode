"""словарь предметной области: значения, общие для API, бизнес-логики и хранения.

Модуль ни от чего не зависит, поэтому его безопасно импортировать из любого слоя.
"""

from enum import StrEnum


class EventType(StrEnum):
    """Вид записи."""

    TASK = "task"
    REMINDER = "reminder"
    MEETING = "meeting"


class EventStatus(StrEnum):
    """Статус выполнения записи."""

    OPEN = "open"
    DONE = "done"


class EventSource(StrEnum):
    """Откуда появилась запись: от пользователя или из импорта истории CSV."""

    USER = "user"
    IMPORT = "import"


class MessageRole(StrEnum):
    """Автор реплики в истории диалога."""

    USER = "user"
    ASSISTANT = "assistant"


class MessageSource(StrEnum):
    """Как пришла реплика пользователя: текстом или голосом (тогда показываем распознанное)."""

    TEXT = "text"
    VOICE = "voice"


class ReplyKind(StrEnum):
    """Как фронту показать ответ ассистента."""

    CONFIRMATION = "confirmation"
    LIST = "list"
    SEARCH_RESULTS = "search_results"
    CLARIFICATION = "clarification"
    CHOICE = "choice"
    CONFIRM_REQUEST = "confirm_request"
    INFO = "info"


class PendingExpectation(StrEnum):
    """Чего ассистент ждёт от пользователя в следующей реплике."""

    DATE = "date"
    TIME = "time"
    DATETIME = "datetime"
    CHOICE = "choice"
    CONFIRM = "confirm"
    TITLE = "title"


class ServiceStatus(StrEnum):
    """Состояние зависимости в проверке живости."""

    OK = "ok"
    FAIL = "fail"
    UNKNOWN = "unknown"
