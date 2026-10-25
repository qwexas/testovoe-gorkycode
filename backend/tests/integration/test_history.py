"""История из CSV: заполнение `seed_events` при старте и копия в каждый новый профиль."""

from datetime import datetime

import httpx
import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.enums import EventSource, EventStatus
from app.core.history_source import read_history_file
from app.factory import create_app
from app.search.placeholders import HashingEmbedder, LowercaseLemmatizer
from app.storage.models import EventRecord, SeedEventRecord
from tests.conftest import BASE_URL, make_settings
from tests.integration.conftest import truncate_seed_events, truncate_user_data

pytestmark = pytest.mark.integration

HISTORY = read_history_file()
PROBE = HISTORY[0]


async def start_app(database_url: str) -> None:
    """Старт и остановка приложения: заготовка заполняется в lifespan."""
    app = create_app(make_settings(database_url))
    async with app.router.lifespan_context(app):
        pass


async def seed_row_versions(db_engine: AsyncEngine) -> list[str]:
    """`xmin` строк заготовки: меняется, только если строку перезаписали."""
    async with db_engine.connect() as connection:
        rows = await connection.execute(text("SELECT xmin::text FROM seed_events ORDER BY id"))
        return list(rows.scalars())


@pytest.fixture
async def empty_seed(database_url: str) -> str:
    await truncate_user_data(database_url)
    await truncate_seed_events(database_url)
    return database_url


class TestSeedEvents:
    async def test_startup_fills_empty_table(self, empty_seed: str, db_engine: AsyncEngine) -> None:
        await start_app(empty_seed)

        async with db_engine.connect() as connection:
            records = (
                await connection.execute(select(SeedEventRecord).order_by(SeedEventRecord.id))
            ).all()
        assert [(row.id, row.type, row.title) for row in records] == [
            (entry.id, entry.type, entry.title) for entry in HISTORY
        ]
        probe = records[0]
        assert probe.starts_at == PROBE.starts_at
        assert probe.ends_at == PROBE.ends_at
        assert probe.lemmas == LowercaseLemmatizer().lemmas(PROBE.title)
        assert probe.embedding == pytest.approx(
            await HashingEmbedder().embed_query(PROBE.title), abs=1e-6
        )

    async def test_next_startup_keeps_table(self, empty_seed: str, db_engine: AsyncEngine) -> None:
        await start_app(empty_seed)
        versions = await seed_row_versions(db_engine)

        await start_app(empty_seed)

        assert await seed_row_versions(db_engine) == versions

    async def test_table_from_other_model_is_rebuilt(
        self, empty_seed: str, db_engine: AsyncEngine
    ) -> None:
        await start_app(empty_seed)
        foreign_vector = await HashingEmbedder().embed_query("совсем другая модель")
        async with db_engine.begin() as connection:
            await connection.execute(
                update(SeedEventRecord)
                .where(SeedEventRecord.id == PROBE.id)
                .values(embedding=foreign_vector)
            )

        await start_app(empty_seed)

        async with db_engine.connect() as connection:
            restored = await connection.scalar(
                select(SeedEventRecord.embedding).where(SeedEventRecord.id == PROBE.id)
            )
        assert restored == pytest.approx(await HashingEmbedder().embed_query(PROBE.title), abs=1e-6)

    async def test_rebuild_keeps_profile_links(
        self, empty_seed: str, db_engine: AsyncEngine
    ) -> None:
        await start_app(empty_seed)
        app = create_app(make_settings(empty_seed))
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url=BASE_URL
        ) as client:
            profile_id = (await client.get("/api/me")).json()["id"]
        async with db_engine.begin() as connection:
            await connection.execute(
                update(SeedEventRecord).values(
                    embedding=await HashingEmbedder().embed_query("совсем другая модель")
                )
            )

        await start_app(empty_seed)

        async with db_engine.connect() as connection:
            linked = await connection.scalar(
                select(func.count()).where(
                    EventRecord.profile_id == profile_id, EventRecord.seed_event_id.is_not(None)
                )
            )
        assert linked == len(HISTORY)


class TestProfileHistory:
    async def test_new_profile_gets_history_linked_to_seed_without_vectors(
        self, client: httpx.AsyncClient, db_engine: AsyncEngine
    ) -> None:
        profile = (await client.get("/api/me")).json()

        assert profile["events_count"] == len(HISTORY)
        async with db_engine.connect() as connection:
            rows = (
                await connection.execute(
                    select(
                        EventRecord.seed_event_id,
                        EventRecord.type,
                        EventRecord.title,
                        EventRecord.starts_at,
                        EventRecord.ends_at,
                        EventRecord.source,
                        EventRecord.embedding.is_(None).label("no_vector"),
                        EventRecord.lemmas.is_(None).label("no_lemmas"),
                    )
                    .where(EventRecord.profile_id == profile["id"])
                    .order_by(EventRecord.id)
                )
            ).all()
        assert [tuple(row[:5]) for row in rows] == [
            (entry.id, entry.type, entry.title, entry.starts_at, entry.ends_at) for entry in HISTORY
        ]
        assert {(row.source, row.no_vector, row.no_lemmas) for row in rows} == {
            (EventSource.IMPORT, True, True)
        }

    async def test_status_depends_on_profile_creation_moment(
        self, client: httpx.AsyncClient, db_engine: AsyncEngine
    ) -> None:
        profile = (await client.get("/api/me")).json()
        created_at = datetime.fromisoformat(profile["created_at"])

        async with db_engine.connect() as connection:
            statuses = dict(
                (
                    await connection.execute(
                        select(EventRecord.seed_event_id, EventRecord.status).where(
                            EventRecord.profile_id == profile["id"]
                        )
                    )
                ).all()
            )
        expected = {
            entry.id: EventStatus.DONE if entry.starts_at < created_at else EventStatus.OPEN
            for entry in HISTORY
        }
        assert statuses == expected
        assert set(expected.values()) == {EventStatus.DONE, EventStatus.OPEN}

    async def test_renamed_history_record_gets_own_index(
        self, client: httpx.AsyncClient, db_engine: AsyncEngine
    ) -> None:
        imported = (await client.get("/api/events", params={"limit": 1})).json()["events"][0]

        await client.patch(f"/api/events/{imported['id']}", json={"title": "Купить тюльпаны"})

        async with db_engine.connect() as connection:
            row = (
                await connection.execute(
                    select(
                        EventRecord.seed_event_id, EventRecord.embedding, EventRecord.lemmas
                    ).where(EventRecord.id == imported["id"])
                )
            ).one()
        assert row.seed_event_id == PROBE.id
        assert row.embedding == pytest.approx(
            await HashingEmbedder().embed_query("Купить тюльпаны"), abs=1e-6
        )
        assert row.lemmas == ["купить", "тюльпаны"]
        found = (await client.get("/api/events", params={"q": "тюльпаны"})).json()["events"]
        assert [event["id"] for event in found] == [imported["id"]]
        old_title = (await client.get("/api/events", params={"q": PROBE.title})).json()["events"]
        assert imported["id"] not in {event["id"] for event in old_title}

    async def test_each_profile_gets_own_copy(
        self,
        client: httpx.AsyncClient,
        other_device: httpx.AsyncClient,
        db_engine: AsyncEngine,
    ) -> None:
        await client.get("/api/me")
        await other_device.get("/api/me")

        async with db_engine.connect() as connection:
            per_profile = (
                await connection.execute(
                    select(EventRecord.profile_id, func.count()).group_by(EventRecord.profile_id)
                )
            ).all()
        assert [count for _, count in per_profile] == [len(HISTORY), len(HISTORY)]
