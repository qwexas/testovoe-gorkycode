"""Проверка живости, когда база недоступна."""

import httpx

from app import __version__


async def test_health_reports_db_failure_without_crashing(
    offline_client: httpx.AsyncClient,
) -> None:
    response = await offline_client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "version": __version__,
        "checks": {"db": "fail", "llm": "unknown", "stt": "unknown", "tts": "unknown"},
    }
