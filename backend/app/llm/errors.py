"""ошибки языковой модели в терминах контракта API."""

from app.core.errors import DomainError, ErrorCode


class LLMUnavailableError(DomainError):
    """модель не ответила или ответила не по схеме даже после повторов (`llm_unavailable`)."""

    code = ErrorCode.LLM_UNAVAILABLE
    default_message = (
        "Не получилось разобрать запрос: языковая модель недоступна. Повторите чуть позже."
    )
