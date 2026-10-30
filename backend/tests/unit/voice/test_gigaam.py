"""`GigaAMSpeechToText` без модели: целиком и по VAD, «не речь», ошибки, очередь, прогрев."""

import asyncio
import threading
import time
from collections.abc import Iterable
from dataclasses import dataclass, field

import numpy as np
import pytest
from numpy.typing import NDArray

from app.core.enums import ServiceStatus
from app.core.errors import AudioUnsupportedError, SpeechToTextUnavailableError
from app.factory import _speech_to_text
from app.voice.gigaam import GigaAMModels, GigaAMSpeechToText
from app.voice.interfaces import AudioClip
from app.voice.settings import SpeechToTextSettings
from app.voice.whisper import WhisperSpeechToText
from tests.unit.voice.audio_samples import AudioSpec, encoded

WEBM = AudioClip(encoded(AudioSpec("webm", "libopus")), "audio/webm")
LONG_WEBM = AudioClip(encoded(AudioSpec("webm", "libopus", seconds=25)), "audio/webm")
SLOW_TRANSCRIPTION_SECONDS = 0.05


@dataclass(frozen=True, slots=True)
class Segment:
    text: str


@dataclass
class FakeGigaAM:
    """Модель-заглушка: запоминает вызовы, отдаёт текст целиком и фрагменты по VAD."""

    text: str = " Добавь встречу с командой завтра в 15:00. "
    segments: tuple[str, ...] = (" Напомни завтра в 10:00 ", " позвонить Ивану. ")
    failure: Exception | None = None
    delay: float = 0.0
    calls: list[str] = field(default_factory=list)
    vad_loads: int = 0
    active: int = 0
    max_active: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock)

    def recognize(self, waveform: NDArray[np.float32], *, sample_rate: int) -> str:
        self._enter("whole", sample_rate)
        return self.text

    def segmented(self) -> "FakeGigaAM.Segmented":
        self.vad_loads += 1
        return FakeGigaAM.Segmented(self)

    @dataclass
    class Segmented:
        model: "FakeGigaAM"

        def recognize(
            self, waveform: NDArray[np.float32], *, sample_rate: int
        ) -> Iterable[Segment]:
            self.model._enter("vad", sample_rate)
            return [Segment(text) for text in self.model.segments]

    def _enter(self, kind: str, sample_rate: int) -> None:
        assert sample_rate == 16_000
        with self.lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        time.sleep(self.delay)
        with self.lock:
            self.active -= 1
        self.calls.append(kind)
        if self.failure is not None:
            raise self.failure

    def models(self) -> GigaAMModels:
        return GigaAMModels(self, self.segmented)


def settings(**overrides: object) -> SpeechToTextSettings:
    return SpeechToTextSettings(_env_file=None, **overrides)  # type: ignore[arg-type]


def recognizer(model: FakeGigaAM, **overrides: object) -> GigaAMSpeechToText:
    return GigaAMSpeechToText(settings(**overrides), load_model=lambda _: model.models())


async def test_short_phrase_is_recognized_whole_without_vad() -> None:
    model = FakeGigaAM()

    text = await recognizer(model).transcribe(WEBM)

    assert text == "Добавь встречу с командой завтра в 15:00."
    assert (model.calls, model.vad_loads) == (["whole"], 0)


async def test_long_recording_is_split_by_vad() -> None:
    model = FakeGigaAM()

    text = await recognizer(model).transcribe(LONG_WEBM)

    assert text == "Напомни завтра в 10:00 позвонить Ивану."
    assert model.calls == ["vad"]


@pytest.mark.parametrize("output", ["", " ", ".", " … "])
async def test_punctuation_without_words_is_no_speech(output: str) -> None:
    assert await recognizer(FakeGigaAM(text=output)).transcribe(WEBM) == ""


async def test_unsupported_audio_fails_before_model_loads() -> None:
    stt = recognizer(FakeGigaAM())

    with pytest.raises(AudioUnsupportedError):
        await stt.transcribe(AudioClip(b"not audio", "audio/webm"))
    assert await stt.check() is ServiceStatus.UNKNOWN


async def test_failed_load_is_unavailable_and_retried_next_time() -> None:
    attempts: list[int] = []
    model = FakeGigaAM()

    def flaky_loader(_: SpeechToTextSettings) -> GigaAMModels:
        attempts.append(1)
        if len(attempts) == 1:
            raise OSError("нет весов")
        return model.models()

    stt = GigaAMSpeechToText(settings(), load_model=flaky_loader)

    with pytest.raises(SpeechToTextUnavailableError):
        await stt.transcribe(WEBM)
    assert await stt.check() is ServiceStatus.FAIL

    assert await stt.transcribe(WEBM) != ""
    assert await stt.check() is ServiceStatus.OK


async def test_model_crash_is_unavailable() -> None:
    stt = recognizer(FakeGigaAM(failure=RuntimeError("ONNX Runtime упал")))

    with pytest.raises(SpeechToTextUnavailableError):
        await stt.transcribe(WEBM)


@pytest.mark.parametrize("limit", [1, 2])
async def test_parallel_phrases_wait_in_queue(limit: int) -> None:
    model = FakeGigaAM(delay=SLOW_TRANSCRIPTION_SECONDS)
    stt = recognizer(model, max_concurrency=limit)

    await asyncio.gather(*(stt.transcribe(WEBM) for _ in range(4)))

    assert model.max_active == limit
    assert len(model.calls) == 4


async def test_warm_up_loads_model_without_transcribing() -> None:
    model = FakeGigaAM()
    stt = recognizer(model)

    await stt.warm_up()

    assert await stt.check() is ServiceStatus.OK
    assert model.calls == []


async def test_warm_up_can_be_switched_off() -> None:
    stt = recognizer(FakeGigaAM(), warm_up_on_startup=False)

    await stt.warm_up()

    assert await stt.check() is ServiceStatus.UNKNOWN


def test_gigaam_is_default_engine_and_whisper_is_switchable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("STT_ENGINE", raising=False)
    assert settings().engine == "gigaam"
    assert settings().gigaam_model == "gigaam-v3-e2e-rnnt"

    monkeypatch.setenv("STT_ENGINE", "gigaam")
    assert isinstance(_speech_to_text(), GigaAMSpeechToText)
    monkeypatch.setenv("STT_ENGINE", "whisper")
    assert isinstance(_speech_to_text(), WhisperSpeechToText)
