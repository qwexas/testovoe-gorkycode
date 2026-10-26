"""Сервис диалога: контекст для парсера, состояние, история, ошибки LLM, лимит, подсказки."""

from datetime import time, timedelta

import pytest

from app.core.dialog.payloads import answer_payload
from app.core.dialog.service import MessageThrottle
from app.core.dialog.state import RECENT_TURNS_LIMIT
from app.core.enums import EventType, MessageRole, MessageSource, PendingExpectation, ReplyKind
from app.core.errors import ErrorCode, TooManyMessagesError
from app.core.rate_limit import SlidingWindowRateLimiter
from app.llm.errors import LLMUnavailableError
from app.nlu.interfaces import Action, DialogTurn
from tests.unit.dialog.support import (
    NOW,
    TODAY,
    TOMORROW,
    DialogHarness,
    at,
    create,
    listing,
    simple,
)

EXAMPLES = (
    "«Напомни завтра в 10 позвонить Ивану», «Что у меня сегодня?» "
    "или «Найди задачу про презентацию»"
)


class TestParserContext:
    async def test_first_turn_has_only_now(self, dialog: DialogHarness) -> None:
        await dialog.say(listing("Что у меня сегодня?"))

        [context] = dialog.parser.contexts
        assert context.now == NOW
        assert context.now.utcoffset() == timedelta(hours=3)
        assert (context.pending, context.pending_question) == (None, None)
        assert (tuple(context.recent), tuple(context.focus)) == ((), ())

    async def test_pending_question_is_passed(self, dialog: DialogHarness) -> None:
        await dialog.say(
            create("Встреча с Иваном завтра", EventType.MEETING, "Встреча с Иваном", date=TOMORROW)
        )

        await dialog.say(listing("Что у меня сегодня?"))

        context = dialog.parser.contexts[-1]
        assert context.pending is PendingExpectation.TIME
        assert context.pending_question == "На какое время поставить встречу?"

    async def test_recent_turns_oldest_first_limited(self, dialog: DialogHarness) -> None:
        for number in range(5):
            await dialog.say(simple(Action.SMALLTALK, f"привет {number}"))

        await dialog.say(simple(Action.SMALLTALK, "последняя"))

        recent = list(dialog.parser.contexts[-1].recent)
        assert len(recent) == RECENT_TURNS_LIMIT
        assert recent[0] == DialogTurn(role="user", text="привет 2")
        assert recent[-2] == DialogTurn(role="user", text="привет 4")
        assert recent[-1].role == "assistant"

    async def test_focus_puts_latest_first(self, dialog: DialogHarness) -> None:
        planned = await dialog.add_event(EventType.MEETING, "Планёрка", at(TODAY, 15))
        await dialog.say(listing("Что у меня сегодня?"))
        created = await dialog.say(create("Купить хлеб", EventType.TASK, "Купить хлеб"))

        await dialog.say(simple(Action.SMALLTALK, "спасибо"))

        focus = dialog.parser.contexts[-1].focus
        assert [event.id for event in focus] == [created.events[0].id, planned.id]
        assert (focus[1].type, focus[1].title, focus[1].starts_at) == (
            EventType.MEETING,
            "Планёрка",
            at(TODAY, 15),
        )

    async def test_deleted_focus_events_are_skipped(self, dialog: DialogHarness) -> None:
        created = await dialog.say(create("Купить хлеб", EventType.TASK, "Купить хлеб"))
        await dialog.storage.events.delete(dialog.profile_id, created.events[0].id)

        await dialog.say(simple(Action.SMALLTALK, "спасибо"))

        assert list(dialog.parser.contexts[-1].focus) == []

    async def test_unreadable_pending_is_forgotten(self, dialog: DialogHarness) -> None:
        await dialog.say(
            create("Встреча с Иваном завтра", EventType.MEETING, "Встреча с Иваном", date=TOMORROW)
        )
        assert dialog.state is not None
        dialog.state.pending = {"format": "old"}

        await dialog.say(simple(Action.SMALLTALK, "привет"))

        assert dialog.parser.contexts[-1].pending is None


class TestHistory:
    async def test_saves_user_and_assistant_messages(self, dialog: DialogHarness) -> None:
        answer = await dialog.answer(listing("Что у меня сегодня?"))

        user, assistant = dialog.storage.messages.messages
        assert (user.role, user.text, user.reply) == (MessageRole.USER, "Что у меня сегодня?", None)
        assert (assistant.role, assistant.text) == (MessageRole.ASSISTANT, answer.reply.text)
        assert assistant.reply == answer_payload(answer)
        assert answer.message_id == assistant.id

    async def test_payload_has_contract_shape(self, dialog: DialogHarness) -> None:
        answer = await dialog.answer(
            create(
                "Встреча завтра в 15", EventType.MEETING, "Планёрка", date=TOMORROW, time=time(15)
            )
        )

        payload = answer_payload(answer)
        assert set(payload) == {
            "message_id",
            "kind",
            "text",
            "recognized_text",
            "events",
            "period",
            "choices",
            "conflicts",
            "pending",
            "undo",
        }
        assert payload["kind"] == "confirmation"
        assert payload["events"][0]["starts_at"] == "2026-10-27T15:00:00+03:00"
        assert payload["undo"]["expires_at"] == "2026-10-26T12:00:30+03:00"

    async def test_list_payload_has_period_from_to(self, dialog: DialogHarness) -> None:
        answer = await dialog.answer(listing("Что у меня сегодня?"))

        assert answer_payload(answer)["period"] == {
            "from": "2026-10-26T00:00:00+03:00",
            "to": "2026-10-27T00:00:00+03:00",
            "label": "сегодня",
        }

    async def test_voice_source_fills_recognized_text(self, dialog: DialogHarness) -> None:
        answer = await dialog.answer(listing("что у меня сегодня"), MessageSource.VOICE)

        assert answer.recognized_text == "что у меня сегодня"

    async def test_history_pages_newest_last(self, dialog: DialogHarness) -> None:
        for number in range(3):
            await dialog.say(simple(Action.SMALLTALK, f"привет {number}"))

        page = await dialog.service.history(dialog.profile_id, limit=2)
        older = await dialog.service.history(dialog.profile_id, limit=10, before_id=page[0].id)

        assert [entry.id for entry in page] == [5, 6]
        assert [entry.id for entry in older] == [1, 2, 3, 4]
        assert page[1].reply is not None and page[1].reply["message_id"] == 6

    async def test_commits_user_message_before_parsing(self, dialog: DialogHarness) -> None:
        dialog.parser.script["Привет"] = LLMUnavailableError()

        with pytest.raises(LLMUnavailableError) as raised:
            await dialog.service.handle(dialog.profile_id, "Привет", MessageSource.TEXT)

        assert raised.value.code is ErrorCode.LLM_UNAVAILABLE
        assert [m.role for m in dialog.storage.messages.messages] == [MessageRole.USER]
        assert dialog.storage.commits == 1
        assert dialog.state is None


class TestThrottle:
    async def test_twenty_messages_per_minute(self, dialog: DialogHarness) -> None:
        dialog.throttle = MessageThrottle()
        for number in range(20):
            await dialog.say(simple(Action.SMALLTALK, f"привет {number}"))

        with pytest.raises(TooManyMessagesError) as raised:
            await dialog.say(simple(Action.SMALLTALK, "ещё"))

        assert raised.value.retry_after_seconds == 60
        assert len(dialog.storage.messages.messages) == 40

    async def test_profiles_are_limited_separately(self, dialog: DialogHarness) -> None:
        throttle = MessageThrottle(SlidingWindowRateLimiter(max_hits=1, window_seconds=60))
        dialog.throttle = throttle
        await dialog.say(simple(Action.SMALLTALK, "привет"))

        other = dialog.profile_id
        dialog.profile_id = type(other)(int=other.int + 1)
        reply = await dialog.say(simple(Action.SMALLTALK, "привет снова"))

        assert reply.kind is ReplyKind.INFO


class TestHints:
    async def test_smalltalk(self, dialog: DialogHarness) -> None:
        reply = await dialog.say(simple(Action.SMALLTALK, "Привет! Что ты умеешь?"))

        assert reply.kind is ReplyKind.INFO
        assert reply.text == (
            f"Я Горький — веду ваши задачи, напоминания и встречи. Скажите, например: {EXAMPLES}."
        )

    async def test_unknown(self, dialog: DialogHarness) -> None:
        reply = await dialog.say(simple(Action.UNKNOWN, "Какая погода в Сочи?"))

        assert reply.kind is ReplyKind.INFO
        assert reply.text == f"Не понял, что сделать. Скажите, например: {EXAMPLES}."

    @pytest.mark.parametrize("action", [Action.CHOOSE, Action.CONFIRM, Action.DENY])
    async def test_follow_up_without_question(self, dialog: DialogHarness, action: Action) -> None:
        reply = await dialog.say(simple(action, "да"))

        assert reply.text.startswith("Не понял, что сделать.")
