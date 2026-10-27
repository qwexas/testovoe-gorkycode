"""Проверка живости сервиса и его зависимостей."""

import asyncio
import logging
from dataclasses import dataclass
from typing import Literal, Protocol

from app.core.enums import ServiceStatus
from app.storage.database import Database

DatabaseStatus = Literal[ServiceStatus.OK, ServiceStatus.FAIL]

logger = logging.getLogger(__name__)


class StatusProbe(Protocol):
    """Проверка одной внешней зависимости (LLM, распознавание, синтез речи)."""

    async def check(self) -> ServiceStatus:
        """`ok` — отвечает, `fail` — недоступна, `unknown` — проверить пока нельзя."""
        ...


@dataclass(frozen=True, slots=True)
class DependencyProbes:
    """Проверки подключённых зависимостей; `None` — зависимость не подключена."""

    llm: StatusProbe | None = None
    stt: StatusProbe | None = None
    tts: StatusProbe | None = None


@dataclass(frozen=True, slots=True)
class HealthReport:
    """Состояние зависимостей; не подключённая зависимость — `unknown`."""

    db: DatabaseStatus
    llm: ServiceStatus = ServiceStatus.UNKNOWN
    stt: ServiceStatus = ServiceStatus.UNKNOWN
    tts: ServiceStatus = ServiceStatus.UNKNOWN


async def check_health(database: Database, probes: DependencyProbes) -> HealthReport:
    """Опрашивает базу и подключённые зависимости одновременно."""
    db_available, llm, stt, tts = await asyncio.gather(
        database.is_available(), _status(probes.llm), _status(probes.stt), _status(probes.tts)
    )
    db_status: DatabaseStatus = ServiceStatus.OK if db_available else ServiceStatus.FAIL
    return HealthReport(db=db_status, llm=llm, stt=stt, tts=tts)


async def _status(probe: StatusProbe | None) -> ServiceStatus:
    if probe is None:
        return ServiceStatus.UNKNOWN
    try:
        return await probe.check()
    except Exception:  # упавшая проверка — это «недоступна», а не 500 у /api/health
        logger.exception("Проверка зависимости упала")
        return ServiceStatus.FAIL
