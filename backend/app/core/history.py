"""история записей, которую получает каждый новый профиль (решение Q22).

1000 записей из CSV лежат в общей таблице `seed_events` вместе с векторами и леммами
названий. `SeedHistoryLoader` заполняет её при старте приложения. `CsvProfileHistory`
даёт новому профилю записи одним `INSERT … SELECT` — только поля записи и ссылку на
заготовку, без векторов: поиск берёт индекс из `seed_events`. Поэтому создание
профиля не ждёт модель эмбеддингов, а профиль не хранит тысячу копий векторов.
"""

import logging
import math
import time
from collections.abc import Sequence
from itertools import batched
from typing import Protocol
from uuid import UUID

from app.core.history_source import HistoryEntry
from app.core.search import SearchService, TitleIndex
from app.storage.database import UnitOfWork
from app.storage.models import SeedEventRecord

INDEX_BATCH_SIZE = 64
"""сколько названий отдавать модели эмбеддингов за раз при заполнении заготовки."""

SAME_EMBEDDER_MIN_SIMILARITY = 0.999
"""если вектор контрольной записи от текущей модели не совпал с сохранённым, модель
сменилась (например, заглушка → настоящая) и заготовку нужно пересчитать."""

logger = logging.getLogger(__name__)


class ProfileHistorySeeder(Protocol):
    """заполняет только что созданный профиль историей в той же транзакции."""

    async def seed(self, storage: UnitOfWork, profile_id: UUID) -> None:
        """добавляет записи истории профилю `profile_id`, не фиксируя транзакцию."""
        ...


class CsvProfileHistory:
    """история из CSV: прошедшие записи — «выполнено», будущие — «открыта», источник — импорт."""

    async def seed(self, storage: UnitOfWork, profile_id: UUID) -> None:
        """добавляет профилю записи истории со ссылками на заготовку."""
        await storage.seed_events.copy_to_profile(profile_id)


class SeedHistoryLoader:
    """готовит `seed_events`: записи из seed-файла с векторами и леммами названий."""

    def __init__(self, search: SearchService, entries: Sequence[HistoryEntry]) -> None:
        self._search = search
        self._entries = entries

    async def ensure_loaded(self, storage: UnitOfWork) -> None:
        """заполняет заготовку, если она пуста или посчитана другой моделью.

        Строки обновляются на месте, поэтому записи истории во всех профилях сразу
        ищутся по новым векторам. Параллельные процессы ждут друг друга на
        advisory-блокировке, и заготовка заполняется один раз.
        """
        await storage.seed_events.lock()
        if await self._is_up_to_date(storage):
            return
        started = time.perf_counter()
        indexes = await self._index_titles()
        records = [_seed_record(entry, indexes[entry.title]) for entry in self._entries]
        await storage.seed_events.save_all(records)
        await storage.commit()
        logger.info(
            "seed_events: %d записей заполнено за %.2f с",
            len(records),
            time.perf_counter() - started,
        )

    async def _is_up_to_date(self, storage: UnitOfWork) -> bool:
        if await storage.seed_events.count() != len(self._entries):
            return False
        if not self._entries:
            return True
        probe = self._entries[0]
        stored = await storage.seed_events.get(probe.id)
        if stored is None or stored.title != probe.title:
            return False
        fresh = await self._search.index_title(probe.title)
        return (
            stored.lemmas == fresh.lemmas
            and _cosine_similarity(stored.embedding, fresh.embedding)
            >= SAME_EMBEDDER_MIN_SIMILARITY
        )

    async def _index_titles(self) -> dict[str, TitleIndex]:
        """индексы уникальных названий: в CSV 1000 записей, но названий меньше."""
        titles = list(dict.fromkeys(entry.title for entry in self._entries))
        indexes: dict[str, TitleIndex] = {}
        for batch in batched(titles, INDEX_BATCH_SIZE):
            indexes.update(zip(batch, await self._search.index_titles(batch), strict=True))
        return indexes


def _seed_record(entry: HistoryEntry, index: TitleIndex) -> SeedEventRecord:
    return SeedEventRecord(
        id=entry.id,
        type=entry.type,
        title=entry.title,
        starts_at=entry.starts_at,
        has_time=entry.has_time,
        ends_at=entry.ends_at,
        embedding=index.embedding,
        lemmas=index.lemmas,
    )


def _cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    norms = math.hypot(*left) * math.hypot(*right)
    if norms == 0:
        return 0.0
    return sum(a * b for a, b in zip(left, right, strict=True)) / norms
