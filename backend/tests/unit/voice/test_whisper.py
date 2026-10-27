"""`WhisperSpeechToText` без модели: декодирование, ошибки, состояние, очередь, параметры."""

import asyncio
import threading
import time
from collections.abc import Iterable
from dataclasses import dataclass, field

import numpy as np
import pytest
from numpy.typing import NDArray

from app.core.enums import ServiceStatus
from app.core.errors import AudioTooLargeError, AudioUnsupportedError, SpeechToTextUnavailableError
from app.voice.interfaces import MAX_AUDIO_BYTES, AudioClip
from app.voice.settings import SpeechToTextSettings
from app.voice.whisper import DOMAIN_PROMPT, WhisperModelLike, WhisperSpeechToText
from tests.unit.voice.audio_samples import AudioSpec, encoded

WEBM = AudioClip(encoded(AudioSpec("webm", "libopus")), "audio/webm")
SLOW_TRANSCRIPTION_SECONDS = 0.05


@dataclass(frozen=True, slots=True)
class Segment:
    text: str


@dataclass
class FakeWhisper:
    """Модель-заглушка: запоминает вызовы и отдаёт заданные отрезки."""

    segments: tuple[str, ...] = (" Добавь встречу", " с командой завтра. ")
    failure: Exception | None = None
    delay: float = 0.0
    calls: list[dict[str, object]] = field(default_factory=list)
    active: int = 0
    max_active: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock)

    def transcribe(
        self, audio: NDArray[np.float32], **options: object
    ) -> tuple[Iterable[Segment], object]:
        with self.lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        time.sleep(self.delay)
        with self.lock:
            self.active -= 1
        self.calls.append({"samples": audio.size, **options})
        if self.failure is not None:
            raise self.failure
        return (Segment(text) for text in self.segments), object()


def settings(**overrides: object) -> SpeechToTextSettings:
    return SpeechToTextSettings(_env_file=None, **overrides)  # type: ignore[arg-type]


def recognizer(model: FakeWhisper, **overrides: object) -> WhisperSpeechToText:
    return WhisperSpeechToText(settings(**overrides), load_model=lambda _: model)


async def test_segments_are_joined_and_stripped() -> None:
    assert await recognizer(FakeWhisper()).transcribe(WEBM) == "Добавь встречу с командой завтра."


async def test_no_segments_means_no_speech() -> None:
    assert await recognizer(FakeWhisper(segments=())).transcribe(WEBM) == ""


async def test_decoding_options_follow_settings() -> None:
    model = FakeWhisper()

    await recognizer(model, beam_size=3).transcribe(WEBM)

    [call] = model.calls
    assert call["language"] == "ru"
    assert call["vad_filter"] is True
    assert call["beam_size"] == 3
    assert call["initial_prompt"] == DOMAIN_PROMPT
    assert call["samples"] == pytest.approx(16_000, rel=0.05)


async def test_domain_prompt_can_be_switched_off() -> None:
    model = FakeWhisper()

    await recognizer(model, domain_prompt=False).transcribe(WEBM)

    assert model.calls[0]["initial_prompt"] is None


async def test_unsupported_audio_fails_before_model_loads() -> None:
    stt = recognizer(FakeWhisper())

    with pytest.raises(AudioUnsupportedError):
        await stt.transcribe(AudioClip(b"not audio", "audio/webm"))
    assert await stt.check() is ServiceStatus.UNKNOWN


async def test_too_large_audio_is_rejected() -> None:
    with pytest.raises(AudioTooLargeError):
        await recognizer(FakeWhisper()).transcribe(
            AudioClip(bytes(MAX_AUDIO_BYTES + 1), "audio/webm")
        )


async def test_status_is_unknown_until_model_loads_then_ok() -> None:
    stt = recognizer(FakeWhisper())
    assert await stt.check() is ServiceStatus.UNKNOWN

    await stt.transcribe(WEBM)

    assert await stt.check() is ServiceStatus.OK


async def test_failed_load_is_unavailable_and_retried_next_time() -> None:
    attempts: list[int] = []
    model = FakeWhisper()

    def flaky_loader(_: SpeechToTextSettings) -> WhisperModelLike:
        attempts.append(1)
        if len(attempts) == 1:
            raise OSError("нет весов")
        return model

    stt = WhisperSpeechToText(settings(), load_model=flaky_loader)

    with pytest.raises(SpeechToTextUnavailableError):
        await stt.transcribe(WEBM)
    assert await stt.check() is ServiceStatus.FAIL

    assert await stt.transcribe(WEBM) != ""
    assert await stt.check() is ServiceStatus.OK


async def test_model_crash_is_unavailable() -> None:
    stt = recognizer(FakeWhisper(failure=RuntimeError("CTranslate2 упал")))

    with pytest.raises(SpeechToTextUnavailableError):
        await stt.transcribe(WEBM)


async def test_model_loads_once_for_parallel_phrases() -> None:
    loads: list[int] = []
    model = FakeWhisper()

    def counting_loader(_: SpeechToTextSettings) -> WhisperModelLike:
        loads.append(1)
        time.sleep(SLOW_TRANSCRIPTION_SECONDS)
        return model

    stt = WhisperSpeechToText(settings(max_concurrency=4), load_model=counting_loader)

    await asyncio.gather(*(stt.transcribe(WEBM) for _ in range(4)))

    assert len(loads) == 1


@pytest.mark.parametrize("limit", [1, 2])
async def test_parallel_phrases_wait_in_queue(limit: int) -> None:
    model = FakeWhisper(delay=SLOW_TRANSCRIPTION_SECONDS)
    stt = recognizer(model, max_concurrency=limit)

    await asyncio.gather(*(stt.transcribe(WEBM) for _ in range(4)))

    assert model.max_active == limit
    assert len(model.calls) == 4


async def test_warm_up_loads_model_without_transcribing() -> None:
    model = FakeWhisper()
    stt = recognizer(model)

    await stt.warm_up()

    assert await stt.check() is ServiceStatus.OK
    assert model.calls == []


async def test_warm_up_can_be_switched_off() -> None:
    model = FakeWhisper()
    stt = recognizer(model, warm_up_on_startup=False)

    await stt.warm_up()

    assert await stt.check() is ServiceStatus.UNKNOWN
    assert model.calls == []


async def test_warm_up_failure_is_logged_not_raised() -> None:
    def broken_loader(_: SpeechToTextSettings) -> WhisperModelLike:
        raise OSError("нет сети")

    stt = WhisperSpeechToText(settings(), load_model=broken_loader)

    await stt.warm_up()

    assert await stt.check() is ServiceStatus.FAIL


def test_settings_read_stt_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STT_MODEL", "small")
    monkeypatch.setenv("STT_BEAM_SIZE", "2")
    monkeypatch.setenv("STT_DOMAIN_PROMPT", "false")

    loaded = settings()

    assert (loaded.model, loaded.beam_size, loaded.domain_prompt) == ("small", 2, False)
