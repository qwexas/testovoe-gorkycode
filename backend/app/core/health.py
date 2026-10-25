"""Проверка живости сервиса и его зависимостей."""

from dataclasses import dataclass
from typing import Literal

from app.core.enums import ServiceStatus
from app.storage.database import Database

DatabaseStatus = Literal[ServiceStatus.OK, ServiceStatus.FAIL]


@dataclass(frozen=True, slots=True)
class HealthReport:
    """Состояние зависимостей. ИИ-сервисы подключатся позже — пока `unknown`."""

    db: DatabaseStatus
    llm: ServiceStatus = ServiceStatus.UNKNOWN
    stt: ServiceStatus = ServiceStatus.UNKNOWN
    tts: ServiceStatus = ServiceStatus.UNKNOWN


async def check_health(database: Database) -> HealthReport:
    """Опрашивает базу; LLM, STT и TTS на этой стадии не проверяются."""
    db_status: DatabaseStatus = (
        ServiceStatus.OK if await database.is_available() else ServiceStatus.FAIL
    )
    return HealthReport(db=db_status)
