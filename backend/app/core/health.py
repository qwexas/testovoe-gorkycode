"""Проверка живости сервиса и его зависимостей."""

from dataclasses import dataclass
from typing import Literal, Protocol

from app.core.enums import ServiceStatus
from app.storage.database import Database

DatabaseStatus = Literal[ServiceStatus.OK, ServiceStatus.FAIL]


class StatusProbe(Protocol):
    """Проверка одной внешней зависимости (LLM, позже STT и TTS)."""

    async def check(self) -> ServiceStatus:
        """`ok` — отвечает, `fail` — недоступна, `unknown` — проверить пока нельзя."""
        ...


@dataclass(frozen=True, slots=True)
class HealthReport:
    """Состояние зависимостей; не подключённая зависимость — `unknown`."""

    db: DatabaseStatus
    llm: ServiceStatus = ServiceStatus.UNKNOWN
    stt: ServiceStatus = ServiceStatus.UNKNOWN
    tts: ServiceStatus = ServiceStatus.UNKNOWN


async def check_health(database: Database, llm: StatusProbe | None) -> HealthReport:
    """Опрашивает базу и LLM (если она подключена); STT и TTS пока не проверяются."""
    db_status: DatabaseStatus = (
        ServiceStatus.OK if await database.is_available() else ServiceStatus.FAIL
    )
    llm_status = ServiceStatus.UNKNOWN if llm is None else await llm.check()
    return HealthReport(db=db_status, llm=llm_status)
