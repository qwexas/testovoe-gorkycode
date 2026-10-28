"""F05: параллельные запросы не перезаписывают контекст диалога."""

import asyncio
import os
from datetime import datetime
from typing import Any, cast
from uuid import UUID, uuid4
from app.core.enums import EventType
from app.storage.models import EventRecord
import pytest
from sqlalchemy import delete, select

from app.core.dialog.service import (
    DialogDependencies,
    DialogService,
    MessageThrottle,
)
from app.core.dialog.state import DialogState
from app.core.enums import MessageRole, MessageSource
from app.core.schedule import MOSCOW
from app.nlu.interfaces import Action, DialogContext, Intent
from app.storage.database import Database
from app.storage.models import ChatMessageRecord, ProfileRecord

FIRST = "Первое сообщение F05"
SECOND = "Второе сообщение F05"

NOW = datetime(2026, 10, 28, 12, 0, tzinfo=MOSCOW)

TIMEOUT = 10.0


class ControlledParser:
    """Останавливает первую команду до разрешения теста."""

    def __init__(self) -> None:
        self.first_entered = asyncio.Event()
        self.release_first = asyncio.Event()
        self.second_entered = asyncio.Event()

        self.contexts: dict[str, DialogContext] = {}

    async def parse(
        self,
        text: str,
        context: DialogContext,
    ) -> Intent:
        self.contexts[text] = context

        if text == FIRST:
            self.first_entered.set()
            await self.release_first.wait()

        elif text == SECOND:
            self.second_entered.set()

        return Intent(
            action=Action.SMALLTALK,
            text=text,
        )


@pytest.mark.asyncio
async def test_parallel_messages_preserve_dialog_context() -> None:
    """Два запроса одного профиля сохраняют обе пары реплик."""

    url = os.getenv("DATABASE_URL_TEST")

    if not url:
        pytest.skip("DATABASE_URL_TEST не задан")

    # Запрещаем случайный запуск на основной базе.
    from sqlalchemy.engine import make_url

    database_name = make_url(url).database

    if database_name != "gorky_test":
        pytest.fail(
            f"Тест должен использовать gorky_test, "
            f"а не {database_name!r}"
        )

    db = Database(url)

    profile_id: UUID = uuid4()
    parser = ControlledParser()

    dependencies = DialogDependencies(
        parser=parser,
        search=cast(Any, object()),
        throttle=MessageThrottle(),
        speech=cast(Any, object()),
        clock=lambda: NOW,
    )

    first_task: asyncio.Task[None] | None = None
    second_task: asyncio.Task[None] | None = None

    second_started = asyncio.Event()
    profile_created = False

    try:
        # 1. Создаём отдельный профиль.
        async with db.unit_of_work() as storage:
            storage._session.add(
                ProfileRecord(
                    id=profile_id,
                    recovery_code_digest=uuid4().hex + uuid4().hex,
                    calendar_token=uuid4().hex + uuid4().hex,
                )
            )
            await storage.commit()

        profile_created = True

        async def send(
            text: str,
            *,
            started: asyncio.Event | None = None,
        ) -> None:
            """Каждый запрос получает отдельную сессию БД."""

            async with db.unit_of_work() as storage:
                if started is not None:
                    started.set()

                service = DialogService(storage, dependencies)

                await service.handle(
                    profile_id,
                    text,
                    MessageSource.TEXT,
                )

        # 2. Запускаем первый запрос.
        first_task = asyncio.create_task(send(FIRST))

        # Дожидаемся, когда A войдёт в парсер.
        await asyncio.wait_for(
            parser.first_entered.wait(),
            timeout=TIMEOUT,
        )

        # В этот момент A ещё не завершён.
        assert not first_task.done()

        # 3. Запускаем второй запрос параллельно.
        second_task = asyncio.create_task(
            send(SECOND, started=second_started)
        )

        await asyncio.wait_for(
            second_started.wait(),
            timeout=TIMEOUT,
        )

        # Даём второму запросу возможность выполнить
        # операции до ожидания блокировки.
        #
        # Здесь нельзя ждать second_entered:
        # при работающем SELECT FOR UPDATE второй
        # запрос ещё не должен войти в парсер.
        await asyncio.sleep(0.1)

        assert not first_task.done()

        # 4. Разрешаем первому запросу завершиться.
        parser.release_first.set()

        # Дожидаемся обоих запросов.
        await asyncio.wait_for(
            asyncio.gather(first_task, second_task),
            timeout=TIMEOUT,
        )

        # Оба запроса должны дойти до парсера.
        assert parser.second_entered.is_set()

        # 5. Читаем данные из новой сессии.
        async with db.unit_of_work() as storage:
            record = await storage.dialog_states.get(profile_id)
            state = DialogState.from_record(record)

            result = await storage._session.scalars(
                select(ChatMessageRecord)
                .where(
                    ChatMessageRecord.profile_id == profile_id
                )
                .order_by(ChatMessageRecord.id)
            )

            messages = list(result.all())

        # 6. Проверяем историю сообщений.
        user_texts = [
            message.text
            for message in messages
            if message.role == MessageRole.USER
        ]

        assistant_messages = [
            message
            for message in messages
            if message.role == MessageRole.ASSISTANT
        ]

        assert len(user_texts) == 2
        assert set(user_texts) == {FIRST, SECOND}

        assert len(assistant_messages) == 2

        # 7. Проверяем сохранённый контекст.
        recent_user_texts = [
            turn.text
            for turn in state.recent
            if turn.role == MessageRole.USER.value
        ]

        assert recent_user_texts == [FIRST, SECOND], (
            "F05: контекст одного из запросов потерян. "
            f"Получено: {recent_user_texts}"
        )

        # 8. Второй парсер должен получить контекст
        # с первой обработанной командой.
        second_context = parser.contexts[SECOND]

        assert any(
            turn.role == MessageRole.USER.value
            and turn.text == FIRST
            for turn in second_context.recent
        ), (
            "F05: второй запрос получил устаревший "
            "контекст диалога"
        )

    finally:
        # На случай ошибки освобождаем первый парсер.
        parser.release_first.set()

        tasks = [
            task
            for task in (first_task, second_task)
            if task is not None
        ]

        for task in tasks:
            if not task.done():
                task.cancel()

        if tasks:
            await asyncio.gather(
                *tasks,
                return_exceptions=True,
            )

        try:
            # Удаляем только профиль данного теста.
            if profile_created:
                async with db.unit_of_work() as storage:
                    await storage._session.execute(
                        delete(ProfileRecord).where(
                            ProfileRecord.id == profile_id
                        )
                    )
                    await storage.commit()

        finally:
            await db.dispose()




class StateParser(ControlledParser):
    """Парсер для проверки pending и focus."""

    def __init__(self, scenario: str) -> None:
        super().__init__()
        self.scenario = scenario

    async def parse(
        self,
        text: str,
        context: DialogContext,
    ) -> Intent:
        # Сохраняем задержку и запись контекста
        # из ControlledParser.
        await super().parse(text, context)

        if text == FIRST:
            if self.scenario == "pending":
                # Команда без названия должна вызвать
                # уточняющий вопрос.
                return Intent(
                    action=Action.CREATE,
                    text=text,
                    event_type=EventType.TASK,
                    title=None,
                )

            # Список событий обновляет фокус.
            return Intent(
                action=Action.LIST,
                text=text,
                event_type=EventType.TASK,
            )

        if self.scenario == "pending":
            # UNKNOWN при существующем pending
            # должен повторить вопрос и сохранить его.
            return Intent(
                action=Action.UNKNOWN,
                text=text,
            )

        # SMALLTALK не создаёт нового фокуса.
        return Intent(
            action=Action.SMALLTALK,
            text=text,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", ["pending", "focus"])
async def test_parallel_requests_preserve_state(
    scenario: str,
) -> None:
    """F05: конкурентная обработка сохраняет pending/focus."""

    from sqlalchemy.engine import make_url

    url = os.getenv("DATABASE_URL_TEST")

    if not url:
        pytest.skip("DATABASE_URL_TEST не задан")

    if make_url(url).database != "gorky_test":
        pytest.fail("Разрешено использовать только gorky_test")

    db = Database(url)
    profile_id = uuid4()
    parser = StateParser(scenario)

    dependencies = DialogDependencies(
        parser=parser,
        search=cast(Any, object()),
        throttle=MessageThrottle(),
        speech=cast(Any, object()),
        clock=lambda: NOW,
    )

    first_task = None
    second_task = None
    profile_created = False
    event_id = None

    try:
        # Подготавливаем профиль.
        async with db.unit_of_work() as storage:
            storage._session.add(
                ProfileRecord(
                    id=profile_id,
                    recovery_code_digest=uuid4().hex + uuid4().hex,
                    calendar_token=uuid4().hex + uuid4().hex,
                )
            )
            await storage.commit()

        profile_created = True

        if scenario == "focus":
            # Создаём настоящее событие.
            # ListingFlow должен найти его.
            async with db.unit_of_work() as storage:
                event = EventRecord(
                    profile_id=profile_id,
                    type=EventType.TASK,
                    title="Контрольная задача F05",
                    starts_at=NOW,
                    has_time=True,
                    ends_at=None,
                )
                storage._session.add(event)
                await storage.flush()
                event_id = event.id
                await storage.commit()

        async def send(text: str) -> None:
            async with db.unit_of_work() as storage:
                service = DialogService(storage, dependencies)

                await service.handle(
                    profile_id,
                    text,
                    MessageSource.TEXT,
                )

        # A доходит до парсера и приостанавливается.
        first_task = asyncio.create_task(send(FIRST))

        await asyncio.wait_for(
            parser.first_entered.wait(),
            timeout=10,
        )

        assert not first_task.done()

        # B начинает обработку того же профиля.
        second_task = asyncio.create_task(send(SECOND))

        await asyncio.sleep(0.1)

        # Разрешаем A завершиться, освобождая
        # транзакционную блокировку.
        parser.release_first.set()

        await asyncio.wait_for(
            asyncio.gather(first_task, second_task),
            timeout=10,
        )

        # Читаем итоговое состояние из новой сессии.
        async with db.unit_of_work() as storage:
            record = await storage.dialog_states.get(
                profile_id
            )

        assert record is not None

        state = DialogState.from_record(record)
        second_context = parser.contexts[SECOND]

        # Обе команды должны остаться в recent.
        recent_users = [
            turn.text
            for turn in state.recent
            if turn.role == MessageRole.USER.value
        ]

        assert recent_users == [FIRST, SECOND]

        if scenario == "pending":
            # Первый запрос создал уточняющий вопрос.
            assert state.pending is not None

            # Второй запрос должен получить
            # существующий pending.
            assert second_context.pending is not None

            assert (
                second_context.pending_question
                == state.pending.question.question
            )

        else:
            assert event_id is not None

            # Первый запрос добавил событие в фокус.
            assert event_id in state.focus_ids

            # Второй запрос увидел этот фокус.
            assert any(
                card.id == event_id
                for card in second_context.focus
            )

    finally:
        parser.release_first.set()

        tasks = [
            task
            for task in (first_task, second_task)
            if task is not None
        ]

        for task in tasks:
            if not task.done():
                task.cancel()

        if tasks:
            await asyncio.gather(
                *tasks,
                return_exceptions=True,
            )

        try:
            if profile_created:
                async with db.unit_of_work() as storage:
                    # Явно удаляем тестовое событие.
                    await storage._session.execute(
                        delete(EventRecord).where(
                            EventRecord.profile_id == profile_id
                        )
                    )
                    await storage._session.execute(
                        delete(ProfileRecord).where(
                            ProfileRecord.id == profile_id
                        )
                    )
                    await storage.commit()
        finally:
            await db.dispose()

