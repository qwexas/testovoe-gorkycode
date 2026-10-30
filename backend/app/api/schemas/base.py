"""базовые классы схем."""

from pydantic import BaseModel, ConfigDict


class RequestModel(BaseModel):
    """Тело запроса: лишние поля — ошибка валидации, а не тихий пропуск."""

    model_config = ConfigDict(extra="forbid")


class ResponseModel(BaseModel):
    """Тело ответа."""
