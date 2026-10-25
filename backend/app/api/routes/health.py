"""Служебные маршруты."""

from fastapi import APIRouter

from app import __version__
from app.api.dependencies import Services
from app.api.schemas.health import HealthChecks, HealthResponse
from app.core.health import check_health

router = APIRouter(tags=["service"])


@router.get(
    "/health",
    name="get_health",
    summary="Проверка живости",
    description="Без профиля. `status` всегда `ok`, состояние зависимостей — в `checks`.",
    response_model=HealthResponse,
)
async def get_health(services: Services) -> HealthResponse:
    report = await check_health(services.database)
    return HealthResponse(
        status="ok",
        version=__version__,
        checks=HealthChecks(db=report.db, llm=report.llm, stt=report.stt, tts=report.tts),
    )
