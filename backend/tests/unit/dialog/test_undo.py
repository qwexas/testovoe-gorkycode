"""Отмена действий (Q33): кнопкой по `action_id` и голосом «отмени», окно 30 секунд."""

from datetime import time, timedelta
from uuid import uuid4

import pytest

from app.core.dialog.models import Reply
from app.core.dialog.undo import UNDO_WINDOW
from app.core.enums import EventStatus, EventType, MessageRole, ReplyKind
from app.core.errors import UndoUnavailableError
from app.nlu.interfaces import Action, When
from tests.unit.dialog.support import (
    FRIDAY,
    NOW,
    TOMORROW,
    DialogHarness,
    about,
    at,
    change,
    create,
    simple,
)


async def create_meeting(dialog: DialogHarness) -> Reply:
    return await dialog.say(
        create(
            "Встреча с командой завтра в 15",
            EventType.MEETING,
            "Встреча с командой",
            date=TOMORROW,
            time=time(15),
        )
    )


def action_id(reply: Reply) -> str:
    assert reply.undo is not None
    return reply.undo.action_id


class TestButton:
    async def test_undo_create_removes_event(self, dialog: DialogHarness) -> None:
        created = await create_meeting(dialog)

        answer = await dialog.service.undo_action(dialog.profile_id, action_id(created))

        assert answer.reply.kind is ReplyKind.CONFIRMATION
        assert answer.reply.text == "Отменил: «Встреча с командой» больше нет в плане."
        assert dialog.event(created.events[0].id) is None
        last = dialog.storage.messages.messages[-1]
        assert (last.id, last.role) == (answer.message_id, MessageRole.ASSISTANT)
        assert last.reply is not None and last.reply["message_id"] == answer.message_id

    async def test_expires_at_is_thirty_seconds(self, dialog: DialogHarness) -> None:
        created = await create_meeting(dialog)

        assert created.undo is not None
        assert created.undo.expires_at == NOW + timedelta(seconds=30) == NOW + UNDO_WINDOW

    async def test_still_works_just_before_expiry(self, dialog: DialogHarness) -> None:
        created = await create_meeting(dialog)
        dialog.clock.now = NOW + UNDO_WINDOW - timedelta(seconds=1)

        answer = await dialog.service.undo_action(dialog.profile_id, action_id(created))

        assert answer.reply.kind is ReplyKind.CONFIRMATION

    async def test_expired_is_unavailable(self, dialog: DialogHarness) -> None:
        created = await create_meeting(dialog)
        dialog.clock.now = NOW + UNDO_WINDOW

        with pytest.raises(UndoUnavailableError, match="Отменить уже нельзя"):
            await dialog.service.undo_action(dialog.profile_id, action_id(created))
        assert dialog.event(created.events[0].id) is not None

    async def test_second_undo_is_unavailable(self, dialog: DialogHarness) -> None:
        created = await create_meeting(dialog)
        await dialog.service.undo_action(dialog.profile_id, action_id(created))

        with pytest.raises(UndoUnavailableError):
            await dialog.service.undo_action(dialog.profile_id, action_id(created))

    async def test_other_profile_cannot_undo(self, dialog: DialogHarness) -> None:
        created = await create_meeting(dialog)

        with pytest.raises(UndoUnavailableError):
            await dialog.service.undo_action(uuid4(), action_id(created))
        assert dialog.event(created.events[0].id) is not None

    async def test_unknown_action(self, dialog: DialogHarness) -> None:
        with pytest.raises(UndoUnavailableError):
            await dialog.service.undo_action(dialog.profile_id, "missing")

    async def test_event_deleted_meanwhile(self, dialog: DialogHarness) -> None:
        created = await create_meeting(dialog)
        await dialog.storage.events.delete(dialog.profile_id, created.events[0].id)

        with pytest.raises(UndoUnavailableError):
            await dialog.service.undo_action(dialog.profile_id, action_id(created))

    async def test_undone_event_leads_focus(self, dialog: DialogHarness) -> None:
        demo = await dialog.add_event(EventType.MEETING, "Демо", at(TOMORROW, 10))
        moved = await dialog.say(
            change(
                Action.RESCHEDULE,
                "Перенеси демо на 12",
                target=about("демо"),
                when=When(time=time(12)),
            )
        )

        await dialog.service.undo_action(dialog.profile_id, action_id(moved))

        assert dialog.state is not None and dialog.state.last_event_ids[0] == demo.id


class TestRevertedChanges:
    async def test_reschedule(self, dialog: DialogHarness) -> None:
        demo = await dialog.add_event(
            EventType.MEETING, "Демо", at(TOMORROW, 10), ends_at=at(TOMORROW, 11, 30)
        )
        moved = await dialog.say(
            change(
                Action.RESCHEDULE,
                "Перенеси демо на пятницу",
                target=about("демо"),
                when=When(date=FRIDAY),
            )
        )

        answer = await dialog.service.undo_action(dialog.profile_id, action_id(moved))

        assert (
            answer.reply.text
            == "Вернул как было: встреча «Демо» — завтра, 27 октября, с 10:00 до 11:30."
        )
        record = dialog.event(demo.id)
        assert record is not None
        assert (record.starts_at, record.ends_at) == (at(TOMORROW, 10), at(TOMORROW, 11, 30))

    async def test_rename(self, dialog: DialogHarness) -> None:
        task = await dialog.add_event(EventType.TASK, "Отчёт")
        renamed = await dialog.say(
            change(
                Action.RENAME,
                "Переименуй отчёт в «Отчёт Ольге»",
                target=about("отчёт"),
                title="Отчёт Ольге",
            )
        )

        await dialog.service.undo_action(dialog.profile_id, action_id(renamed))

        record = dialog.event(task.id)
        assert record is not None and record.title == "Отчёт"

    async def test_complete(self, dialog: DialogHarness) -> None:
        task = await dialog.add_event(EventType.TASK, "Купить билеты")
        done = await dialog.say(change(Action.COMPLETE, "Билеты купил", target=about("билеты")))

        await dialog.service.undo_action(dialog.profile_id, action_id(done))

        record = dialog.event(task.id)
        assert record is not None and record.status is EventStatus.OPEN

    async def test_delete_restores_same_record(self, dialog: DialogHarness) -> None:
        task = await dialog.add_event(
            EventType.TASK, "Купить билеты", at(FRIDAY, 0), has_time=False, status=EventStatus.DONE
        )
        await dialog.say(change(Action.DELETE, "Удали билеты", target=about("билеты")))
        deleted = await dialog.say(simple(Action.CONFIRM, "да"))

        answer = await dialog.service.undo_action(dialog.profile_id, action_id(deleted))

        assert answer.reply.text == "Вернул задачу «Купить билеты»."
        record = dialog.event(task.id)
        assert record is not None
        assert (record.title, record.starts_at, record.has_time, record.status) == (
            "Купить билеты",
            at(FRIDAY, 0),
            False,
            EventStatus.DONE,
        )
        assert record.created_at == task.created_at


class TestVoice:
    async def test_undo_latest_action(self, dialog: DialogHarness) -> None:
        created = await create_meeting(dialog)

        reply = await dialog.say(simple(Action.UNDO, "Отмени"))

        assert reply.kind is ReplyKind.CONFIRMATION
        assert reply.text == "Отменил: «Встреча с командой» больше нет в плане."
        assert dialog.event(created.events[0].id) is None

    async def test_undo_takes_most_recent_of_several(self, dialog: DialogHarness) -> None:
        first = await create_meeting(dialog)
        dialog.clock.now = NOW + timedelta(seconds=5)
        second = await dialog.say(create("Купить хлеб", EventType.TASK, "Купить хлеб"))

        await dialog.say(simple(Action.UNDO, "Верни как было"))

        assert dialog.event(second.events[0].id) is None
        assert dialog.event(first.events[0].id) is not None

    async def test_nothing_to_undo(self, dialog: DialogHarness) -> None:
        reply = await dialog.say(simple(Action.UNDO, "Отмени"))

        assert (reply.kind, reply.text) == (ReplyKind.INFO, "Отменять нечего.")

    async def test_too_late(self, dialog: DialogHarness) -> None:
        await create_meeting(dialog)
        dialog.clock.now = NOW + UNDO_WINDOW + timedelta(seconds=1)

        reply = await dialog.say(simple(Action.UNDO, "Отмени"))

        assert (reply.kind, reply.text) == (ReplyKind.INFO, "Отменить уже нельзя.")

    async def test_expired_actions_are_forgotten_on_next_action(
        self, dialog: DialogHarness
    ) -> None:
        await create_meeting(dialog)
        dialog.clock.now = NOW + timedelta(minutes=5)

        await dialog.say(create("Купить хлеб", EventType.TASK, "Купить хлеб"))

        assert len(dialog.storage.undo_actions.actions) == 1
