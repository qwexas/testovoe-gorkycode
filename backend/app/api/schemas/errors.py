"""Единый формат ошибок API."""

from pydantic import Field

from app.api.schemas.base import ResponseModel
from app.core.errors import ErrorCode


class ErrorBody(ResponseModel):
    """Код ошибки из контракта и сообщение для пользователя."""

    code: ErrorCode
    message: str = Field(description="Сообщение по-русски, пригодное для показа пользователю")


class ErrorResponse(ResponseModel):
    """`{"error": {"code": …, "message": …}}`."""

    error: ErrorBody
