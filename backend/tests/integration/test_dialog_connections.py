"""H2: пока LLM разбирает реплику, соединение с БД возвращено в пул."""

import asyncio
import os
from dataclasses import replace
from typing import Any, cast
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import delete
from sqlalchemy.engine import make_url
from sqlalchemy.pool import QueuePool

from app.core.dialog.service import DialogDependencies, DialogService, MessageThrottle
from app.core.enums import MessageSource
from app.storage.database import Database
from app.storage.models import ChatMessageRecord, ProfileRecord
from tests.integration.test_dialog_race import FIRST, NOW, TIMEOUT, ControlledParser


@pytest.mark.integration
async def test_authenticated_chat_releases_connection_before_parse(
    app: FastAPI, profile_client: httpx.AsyncClient
) -> None:
    """M1 и H2: проверка cookie не удерживает соединение во время HTTP-диалога."""
    parser = ControlledParser()
    services = app.state.services
    app.state.services = replace(services, intent_parser=parser)
    pool = cast(QueuePool, services.database._engine.pool)
    task = asyncio.create_task(profile_client.post("/api/chat", json={"text": FIRST}))
    try:
        await asyncio.wait_for(parser.first_entered.wait(), timeout=TIMEOUT)
        assert pool.checkedout() == 0, "Проверка сессии удерживает соединение во время LLM"
        parser.release_first.set()
        response = await asyncio.wait_for(task, timeout=TIMEOUT)
        assert response.status_code == 200, response.text
    finally:
        parser.release_first.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_parse_does_not_hold_database_connection() -> None:
    url = os.getenv("DATABASE_URL_TEST")
    if not url:
        pytest.skip("DATABASE_URL_TEST не задан")
    if make_url(url).database != "gorky_test":
        pytest.fail("Тест должен использовать gorky_test")

    db = Database(url)
    pool = cast(QueuePool, db._engine.pool)
    profile_id = uuid4()
    parser = ControlledParser()
    dependencies = DialogDependencies(
        parser=parser,
        search=cast(Any, object()),
        throttle=MessageThrottle(),
        speech=cast(Any, object()),
        clock=lambda: NOW,
    )

    async def send() -> None:
        async with db.unit_of_work() as storage:
            await DialogService(storage, dependencies).handle(profile_id, FIRST, MessageSource.TEXT)

    try:
        async with db.unit_of_work() as storage:
            storage._session.add(
                ProfileRecord(
                    id=profile_id,
                    recovery_code_digest=uuid4().hex + uuid4().hex,
                    calendar_token=uuid4().hex + uuid4().hex,
                )
            )
            await storage.commit()

        task = asyncio.create_task(send())
        await asyncio.wait_for(parser.first_entered.wait(), timeout=TIMEOUT)
        assert pool.checkedout() == 0, "Во время разбора занято соединение с БД"

        parser.release_first.set()
        await asyncio.wait_for(task, timeout=TIMEOUT)
    finally:
        parser.release_first.set()
        async with db.unit_of_work() as storage:
            await storage._session.execute(
                delete(ChatMessageRecord).where(ChatMessageRecord.profile_id == profile_id)
            )
            await storage._session.execute(
                delete(ProfileRecord).where(ProfileRecord.id == profile_id)
            )
            await storage.commit()
        await db.dispose()
