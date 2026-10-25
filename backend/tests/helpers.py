"""Проверки, общие для тестов API."""

import httpx

from app.core.errors import ErrorCode


def assert_error(response: httpx.Response, status_code: int, code: ErrorCode) -> None:
    """Ответ — ошибка в едином формате контракта с непустым сообщением."""
    assert response.status_code == status_code, response.text
    body = response.json()
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message"}
    assert body["error"]["code"] == code
    assert body["error"]["message"]
