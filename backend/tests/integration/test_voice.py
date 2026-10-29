"""Голос через API на настоящем Postgres: запись → распознавание → ответ → история без аудио.

Распознавание подменено `FakeSpeechToText`, разбор — `FakeIntentParser`: проверяются
HTTP, бизнес-логика и хранение, а не модели.
"""

from dataclasses import replace
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.dialog.service import MessageThrottle
from app.core.errors import ErrorCode
from app.core.rate_limit import SlidingWindowRateLimiter
from app.nlu.interfaces import Action
from app.storage.models import ChatMessageRecord
from tests.helpers import assert_error
from tests.unit.dialog.support import FakeIntentParser, FakeSpeechToText, simple

pytestmark = pytest.mark.integration

RECORD = b"\x1a\x45\xdf\xa3 webm voice record"
PHRASE = "Привет! Что ты умеешь?"


@pytest.fixture
def speech(app: FastAPI) -> FakeSpeechToText:
    """Распознавание по сценарию теста вместо Whisper."""
    fake = FakeSpeechToText()
    fake.script[RECORD] = PHRASE
    app.state.services = replace(app.state.services, speech_to_text=fake)
    return fake


@pytest.fixture
def parser(app: FastAPI) -> FakeIntentParser:
    fake = FakeIntentParser()
    fake.script[PHRASE] = simple(Action.SMALLTALK, PHRASE)
    app.state.services = replace(app.state.services, intent_parser=fake)
    return fake


async def send_voice(client: httpx.AsyncClient, record: bytes = RECORD) -> httpx.Response:
    return await client.post(
        "/api/voice", files={"audio": ("voice.webm", record, "audio/webm;codecs=opus")}
    )


async def dialog_messages(client: httpx.AsyncClient) -> list[dict[str, Any]]:
    response = await client.get("/api/dialog")
    assert response.status_code == 200, response.text
    messages: list[dict[str, Any]] = response.json()["messages"]
    return messages


@pytest.mark.usefixtures("parser")
async def test_voice_round_trip_keeps_only_text(
    client: httpx.AsyncClient, speech: FakeSpeechToText, db_engine: AsyncEngine
) -> None:
    response = await send_voice(client)

    assert response.status_code == 200, response.text
    reply = response.json()
    assert reply["recognized_text"] == PHRASE
    assert reply["kind"] == "info"
    assert reply["text"].startswith("Я Горький")
    assert [(clip.data, clip.content_type) for clip in speech.clips] == [(RECORD, "audio/webm")]

    user, assistant = await dialog_messages(client)
    assert (user["role"], user["text"], user["reply"]) == ("user", PHRASE, None)
    assert assistant["reply"] == reply

    async with db_engine.connect() as connection:
        texts = (await connection.execute(select(ChatMessageRecord.text))).scalars().all()
    assert PHRASE in texts
    assert all("webm voice record" not in text for text in texts)


@pytest.mark.usefixtures("parser")
async def test_silence_is_422_and_history_stays_empty(
    client: httpx.AsyncClient, speech: FakeSpeechToText
) -> None:
    speech.script[RECORD] = "  "

    response = await send_voice(client)

    assert_error(response, 422, ErrorCode.SPEECH_NOT_RECOGNIZED)
    assert response.json()["error"]["message"] == "Не расслышал, повторите, пожалуйста."
    assert await dialog_messages(client) == []


@pytest.mark.usefixtures("parser")
async def test_voice_and_chat_share_the_limit(
    app: FastAPI, client: httpx.AsyncClient, speech: FakeSpeechToText
) -> None:
    limiter = SlidingWindowRateLimiter(max_hits=2, window_seconds=60)
    app.state.services = replace(app.state.services, message_throttle=MessageThrottle(limiter))
    assert (await client.post("/api/chat", json={"text": PHRASE})).status_code == 200
    assert (await send_voice(client)).status_code == 200

    response = await send_voice(client)

    assert_error(response, 429, ErrorCode.RATE_LIMITED)
    assert response.headers["retry-after"] == "60"
    assert len(speech.clips) == 1


async def test_disabled_stt_is_503(client: httpx.AsyncClient) -> None:
    response = await send_voice(client)

    assert_error(response, 503, ErrorCode.STT_UNAVAILABLE)
    assert "set-cookie" not in response.headers


@pytest.fixture(name="client")
def authenticated_client(profile_client: httpx.AsyncClient) -> httpx.AsyncClient:
    """Операции профиля проверяются после явного создания, без скрытого onboarding."""
    return profile_client


@pytest.fixture(name="other_device")
def authenticated_other_device(other_profile_client: httpx.AsyncClient) -> httpx.AsyncClient:
    return other_profile_client
