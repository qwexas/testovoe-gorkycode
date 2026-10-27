"""Выбор моделей речи в `app.factory` (`VOICE_BACKEND`), `/api/health` и HTTP голоса без базы.

`/api/voice` до распознавания и `/api/tts` целиком не обращаются к базе, поэтому
проверяются на приложении без Postgres с известным текущим профилем.
"""

import logging
import sys
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime
from types import ModuleType
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI

from app.api.dependencies import AppServices, get_current_profile
from app.config import VoiceBackend
from app.core.enums import ServiceStatus
from app.core.errors import ErrorCode
from app.core.profiles import ProfileCard
from app.core.rate_limit import SlidingWindowRateLimiter
from app.core.speech import SynthesisThrottle
from app.factory import create_app
from app.voice.interfaces import AudioClip
from tests.conftest import UNREACHABLE_DATABASE_URL, make_settings
from tests.helpers import assert_error

VOICES = ("xenia", "baya")


class ReadyTextToSpeech:
    """Синтезатор-фейк: OGG-заглушка с текстом внутри."""

    def __init__(self) -> None:
        self.requests: list[tuple[str, str | None]] = []

    @property
    def voices(self) -> Sequence[str]:
        return VOICES

    async def synthesize(self, text: str, voice: str | None) -> AudioClip:
        self.requests.append((text, voice))
        return AudioClip(data=b"OggS" + text.encode(), content_type="audio/ogg")

    async def check(self) -> ServiceStatus:
        return ServiceStatus.OK


class ReadySpeechToText:
    async def transcribe(self, audio: AudioClip) -> str:
        return "Что у меня сегодня?"

    async def check(self) -> ServiceStatus:
        return ServiceStatus.OK


class BrokenModel:
    def __init__(self) -> None:
        raise RuntimeError("веса не скачаны")


def voice_services(backend: VoiceBackend) -> AppServices:
    settings = make_settings(
        UNREACHABLE_DATABASE_URL, voice_backend=backend, load_history_on_startup=False
    )
    services: AppServices = create_app(settings).state.services
    return services


def fake_module(name: str, **attributes: object) -> ModuleType:
    module = ModuleType(name)
    for attribute, value in attributes.items():
        setattr(module, attribute, value)
    return module


@pytest.fixture
def known_profile_app(offline_app: FastAPI) -> FastAPI:
    profile = ProfileCard(
        id=uuid4(), created_at=datetime.now(UTC), events_count=0, calendar_token="token"
    )
    offline_app.dependency_overrides[get_current_profile] = lambda: profile
    return offline_app


@pytest.fixture
def tts(known_profile_app: FastAPI) -> ReadyTextToSpeech:
    fake = ReadyTextToSpeech()
    services = known_profile_app.state.services
    known_profile_app.state.services = replace(services, text_to_speech=fake)
    return fake


class TestFactory:
    async def test_disabled_voice_has_no_probes_and_no_voices(self) -> None:
        services = voice_services(VoiceBackend.DISABLED)

        assert services.probes.stt is None and services.probes.tts is None
        assert services.text_to_speech.voices == ()

    async def test_missing_modules_fall_back_with_warning(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        monkeypatch.setitem(sys.modules, "app.voice.whisper", None)
        monkeypatch.setitem(sys.modules, "app.voice.silero", None)

        with caplog.at_level(logging.WARNING, logger="app.factory"):
            services = voice_services(VoiceBackend.REAL)

        assert "Модель речи для /api/voice недоступна" in caplog.text
        assert "Модель речи для /api/tts недоступна" in caplog.text
        assert services.probes.stt is not None and services.probes.tts is not None
        assert await services.probes.stt.check() is ServiceStatus.FAIL
        assert await services.probes.tts.check() is ServiceStatus.FAIL

    async def test_model_that_fails_to_build_falls_back(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        whisper = fake_module("app.voice.whisper", WhisperSpeechToText=BrokenModel)
        monkeypatch.setitem(sys.modules, "app.voice.whisper", whisper)
        monkeypatch.setitem(sys.modules, "app.voice.silero", None)

        with caplog.at_level(logging.WARNING, logger="app.factory"):
            services = voice_services(VoiceBackend.REAL)

        assert "веса не скачаны" in caplog.text
        assert await services.speech_to_text.check() is ServiceStatus.FAIL

    async def test_real_models_are_used_and_probed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setitem(
            sys.modules,
            "app.voice.whisper",
            fake_module("app.voice.whisper", WhisperSpeechToText=ReadySpeechToText),
        )
        monkeypatch.setitem(
            sys.modules,
            "app.voice.silero",
            fake_module("app.voice.silero", SileroTextToSpeech=ReadyTextToSpeech),
        )

        services = voice_services(VoiceBackend.REAL)

        assert isinstance(services.speech_to_text, ReadySpeechToText)
        assert isinstance(services.text_to_speech, ReadyTextToSpeech)
        assert services.probes.stt is services.speech_to_text
        assert services.probes.tts is services.text_to_speech


class TestHealth:
    async def test_voice_checks_come_from_models(
        self, offline_app: FastAPI, offline_client: httpx.AsyncClient
    ) -> None:
        services = offline_app.state.services
        offline_app.state.services = replace(
            services,
            probes=replace(services.probes, stt=ReadySpeechToText(), tts=ReadyTextToSpeech()),
        )

        response = await offline_client.get("/api/health")

        assert response.json()["checks"] == {
            "db": "fail",
            "llm": "unknown",
            "stt": "ok",
            "tts": "ok",
        }

    async def test_crashing_check_is_fail_not_500(
        self, offline_app: FastAPI, offline_client: httpx.AsyncClient
    ) -> None:
        class CrashingProbe:
            async def check(self) -> ServiceStatus:
                raise RuntimeError("проверка упала")

        services = offline_app.state.services
        offline_app.state.services = replace(
            services, probes=replace(services.probes, stt=CrashingProbe())
        )

        response = await offline_client.get("/api/health")

        assert response.status_code == 200
        assert response.json()["checks"]["stt"] == "fail"


class TestSpeechEndpoint:
    async def test_returns_ogg_without_caching(
        self, tts: ReadyTextToSpeech, offline_client: httpx.AsyncClient
    ) -> None:
        response = await offline_client.post(
            "/api/tts", json={"text": "  Готово.  ", "voice": "baya"}
        )

        assert response.status_code == 200
        assert response.headers["content-type"] == "audio/ogg"
        assert response.headers["cache-control"] == "no-store"
        assert response.content == b"OggS" + "Готово.".encode()
        assert tts.requests == [("Готово.", "baya")]

    async def test_unknown_voice_is_422(
        self, tts: ReadyTextToSpeech, offline_client: httpx.AsyncClient
    ) -> None:
        response = await offline_client.post("/api/tts", json={"text": "Готово.", "voice": "robot"})

        assert_error(response, 422, ErrorCode.VALIDATION_ERROR)
        assert tts.requests == []

    async def test_over_limit_is_429_with_retry_after(
        self, known_profile_app: FastAPI, tts: ReadyTextToSpeech, offline_client: httpx.AsyncClient
    ) -> None:
        limiter = SlidingWindowRateLimiter(max_hits=1, window_seconds=60)
        known_profile_app.state.services = replace(
            known_profile_app.state.services, synthesis_throttle=SynthesisThrottle(limiter)
        )
        await offline_client.post("/api/tts", json={"text": "Раз."})

        response = await offline_client.post("/api/tts", json={"text": "Два."})

        assert_error(response, 429, ErrorCode.RATE_LIMITED)
        assert response.headers["retry-after"] == "60"

    async def test_disabled_tts_is_503(
        self, known_profile_app: FastAPI, offline_client: httpx.AsyncClient
    ) -> None:
        response = await offline_client.post("/api/tts", json={"text": "Готово."})

        assert_error(response, 503, ErrorCode.TTS_UNAVAILABLE)


class TestVoiceEndpointWithoutDatabase:
    async def test_disabled_stt_is_503(
        self, known_profile_app: FastAPI, offline_client: httpx.AsyncClient
    ) -> None:
        response = await offline_client.post(
            "/api/voice", files={"audio": ("voice.webm", b"\x1a\x45\xdf\xa3", "audio/webm")}
        )

        assert_error(response, 503, ErrorCode.STT_UNAVAILABLE)

    async def test_unsupported_format_is_415(
        self, known_profile_app: FastAPI, offline_client: httpx.AsyncClient
    ) -> None:
        response = await offline_client.post(
            "/api/voice", files={"audio": ("voice.txt", b"hello", "text/plain")}
        )

        assert_error(response, 415, ErrorCode.AUDIO_UNSUPPORTED)

    async def test_too_large_is_413(
        self, known_profile_app: FastAPI, offline_client: httpx.AsyncClient
    ) -> None:
        big = b"\x00" * (10 * 1024 * 1024 + 1)

        response = await offline_client.post(
            "/api/voice", files={"audio": ("voice.webm", big, "audio/webm")}
        )

        assert_error(response, 413, ErrorCode.AUDIO_TOO_LARGE)
