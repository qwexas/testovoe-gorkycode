"""Проверка живости с настоящей базой."""

import httpx
import pytest

pytestmark = pytest.mark.integration


async def test_health_reports_db_ok(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["checks"] == {
        "db": "ok",
        "llm": "unknown",
        "stt": "unknown",
        "tts": "unknown",
    }
    assert "set-cookie" not in response.headers
