"""Голосовая реплика в диалоге: распознанный текст, история без аудио, общий лимит, ошибки."""

import pytest

from app.core.dialog.service import MessageThrottle
from app.core.enums import MessageRole, MessageSource, ReplyKind
from app.core.errors import (
    SpeechNotRecognizedError,
    SpeechToTextUnavailableError,
    TooManyMessagesError,
)
from app.core.rate_limit import SlidingWindowRateLimiter
from app.nlu.interfaces import Action
from app.voice.interfaces import AudioClip
from tests.unit.dialog.support import DialogHarness, simple

RECORD = AudioClip(data=b"webm-voice-record", content_type="audio/webm")
PHRASE = "Что у меня сегодня?"


@pytest.fixture
def voiced(dialog: DialogHarness) -> DialogHarness:
    """Диалог, где запись `RECORD` распознаётся как `PHRASE`."""
    dialog.speech.script[RECORD.data] = f"  {PHRASE} "
    dialog.parser.script[PHRASE] = simple(Action.SMALLTALK, PHRASE)
    return dialog


async def test_recognized_phrase_is_answered_like_text(voiced: DialogHarness) -> None:
    answer = await voiced.service.handle_voice(voiced.profile_id, RECORD)

    assert answer.recognized_text == PHRASE
    assert answer.reply.kind is ReplyKind.INFO
    assert [context.now for context in voiced.parser.contexts] == [voiced.clock.now]
    assert voiced.speech.clips == [RECORD]


async def test_history_keeps_only_recognized_text(voiced: DialogHarness) -> None:
    answer = await voiced.service.handle_voice(voiced.profile_id, RECORD)

    user, assistant = voiced.storage.messages.messages
    assert (user.role, user.text, user.reply) == (MessageRole.USER, PHRASE, None)
    assert assistant.reply is not None
    assert assistant.reply["recognized_text"] == PHRASE
    assert assistant.reply["message_id"] == answer.message_id


async def test_silence_saves_nothing(dialog: DialogHarness) -> None:
    dialog.speech.script[RECORD.data] = "   "

    with pytest.raises(SpeechNotRecognizedError):
        await dialog.service.handle_voice(dialog.profile_id, RECORD)

    assert dialog.storage.messages.messages == []
    assert dialog.parser.contexts == []


async def test_stt_failure_saves_nothing(dialog: DialogHarness) -> None:
    dialog.speech.script[RECORD.data] = SpeechToTextUnavailableError()

    with pytest.raises(SpeechToTextUnavailableError):
        await dialog.service.handle_voice(dialog.profile_id, RECORD)

    assert dialog.storage.messages.messages == []


async def test_limit_is_shared_with_text_and_checked_before_recognition(
    voiced: DialogHarness,
) -> None:
    voiced.throttle = MessageThrottle(SlidingWindowRateLimiter(max_hits=2, window_seconds=60))
    await voiced.service.handle(voiced.profile_id, PHRASE, MessageSource.TEXT)
    await voiced.service.handle_voice(voiced.profile_id, RECORD)

    with pytest.raises(TooManyMessagesError):
        await voiced.service.handle_voice(voiced.profile_id, RECORD)

    assert len(voiced.speech.clips) == 1


async def test_unrecognized_record_counts_toward_limit(dialog: DialogHarness) -> None:
    dialog.throttle = MessageThrottle(SlidingWindowRateLimiter(max_hits=1, window_seconds=60))
    with pytest.raises(SpeechNotRecognizedError):
        await dialog.service.handle_voice(dialog.profile_id, RECORD)

    with pytest.raises(TooManyMessagesError):
        await dialog.service.handle_voice(dialog.profile_id, RECORD)
