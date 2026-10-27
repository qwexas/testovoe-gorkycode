"""`SileroTextToSpeech` без модели: голоса, нормализация, куски, OGG, ошибки, файл модели."""

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pytest
from numpy.typing import NDArray

from app.core.enums import ServiceStatus
from app.core.errors import TextToSpeechUnavailableError, UnknownVoiceError
from app.voice import silero
from app.voice.audio import SPEECH_SAMPLE_RATE, decode_speech
from app.voice.settings import SILERO_VOICES, TextToSpeechSettings
from app.voice.silero import (
    EMPTY_SPEECH_SECONDS,
    PAUSE_BETWEEN_CHUNKS_SECONDS,
    ModelChecksumError,
    SileroModelLike,
    SileroTextToSpeech,
    ensure_model_file,
    joined_with_pauses,
)
from app.voice.text_normalizer import EN_DASH, MAX_CHUNK_CHARS
from tests.unit.voice.audio_samples import tone

SECONDS_PER_CHUNK = 0.5
DURATION_PRECISION_SECONDS = 0.1


@dataclass
class Tensor:
    samples: NDArray[np.float32]

    def numpy(self) -> NDArray[np.float32]:
        return self.samples


@dataclass
class FakeSilero:
    """Модель-заглушка: на каждый кусок текста — полсекунды тона."""

    failure: Exception | None = None
    calls: list[dict[str, object]] = field(default_factory=list)

    def apply_tts(
        self, *, text: str, speaker: str, sample_rate: int, put_accent: bool, put_yo: bool
    ) -> Tensor:
        self.calls.append(
            {"text": text, "speaker": speaker, "sample_rate": sample_rate, "accent": put_accent}
        )
        if self.failure is not None:
            raise self.failure
        return Tensor(tone(SECONDS_PER_CHUNK, sample_rate))


def synthesizer(model: FakeSilero, **overrides: object) -> SileroTextToSpeech:
    settings = TextToSpeechSettings(_env_file=None, **overrides)  # type: ignore[arg-type]
    return SileroTextToSpeech(settings, load_model=lambda _: model)


def seconds_of(data: bytes) -> float:
    return decode_speech(data).size / SPEECH_SAMPLE_RATE


async def test_reply_is_ogg_opus_of_spoken_text() -> None:
    model = FakeSilero()

    clip = await synthesizer(model).synthesize("Встреча — завтра в 15:00.", None)

    assert clip.content_type == "audio/ogg"
    assert clip.data.startswith(b"OggS")
    assert seconds_of(clip.data) == pytest.approx(SECONDS_PER_CHUNK, abs=DURATION_PRECISION_SECONDS)
    [call] = model.calls
    assert call["text"] == f"Встреча {EN_DASH} завтра в пятнадцать ноль-ноль."
    assert call["accent"] is True
    assert call["sample_rate"] == 48_000


async def test_default_voice_comes_first_and_is_used() -> None:
    model = FakeSilero()
    tts = synthesizer(model, voice="baya")

    await tts.synthesize("Привет.", None)

    assert tts.voices[0] == "baya"
    assert sorted(tts.voices) == sorted(SILERO_VOICES)
    assert model.calls[0]["speaker"] == "baya"


async def test_requested_voice_is_used() -> None:
    model = FakeSilero()

    await synthesizer(model).synthesize("Привет.", "aidar")

    assert model.calls[0]["speaker"] == "aidar"


async def test_unknown_voice_is_rejected_without_model() -> None:
    tts = synthesizer(FakeSilero())

    with pytest.raises(UnknownVoiceError):
        await tts.synthesize("Привет.", "eugene")
    assert await tts.check() is ServiceStatus.UNKNOWN


def test_settings_reject_unknown_default_voice() -> None:
    with pytest.raises(ValueError, match="голос"):
        TextToSpeechSettings(_env_file=None, voice="eugene")


async def test_long_reply_is_spoken_in_chunks_with_pauses() -> None:
    model = FakeSilero()
    sentence = "Слово " * 40 + "конец."
    text = " ".join([sentence] * 8)

    clip = await synthesizer(model).synthesize(text, None)

    assert len(model.calls) > 1
    assert all(len(str(call["text"])) <= MAX_CHUNK_CHARS for call in model.calls)
    expected = len(model.calls) * SECONDS_PER_CHUNK + (len(model.calls) - 1) * (
        PAUSE_BETWEEN_CHUNKS_SECONDS
    )
    assert seconds_of(clip.data) == pytest.approx(expected, abs=DURATION_PRECISION_SECONDS)


async def test_text_without_words_is_short_silence() -> None:
    model = FakeSilero()

    clip = await synthesizer(model).synthesize("🙂 …", None)

    assert model.calls == []
    assert seconds_of(clip.data) == pytest.approx(
        EMPTY_SPEECH_SECONDS, abs=DURATION_PRECISION_SECONDS
    )
    assert np.abs(decode_speech(clip.data)).max() < 0.01


async def test_model_crash_is_unavailable() -> None:
    tts = synthesizer(FakeSilero(failure=ValueError("Model couldn't generate your text")))

    with pytest.raises(TextToSpeechUnavailableError):
        await tts.synthesize("Привет.", None)


async def test_failed_load_is_unavailable_with_fail_status() -> None:
    def broken_loader(_: TextToSpeechSettings) -> SileroModelLike:
        raise OSError("нет сети")

    tts = SileroTextToSpeech(TextToSpeechSettings(_env_file=None), load_model=broken_loader)

    with pytest.raises(TextToSpeechUnavailableError):
        await tts.synthesize("Привет.", None)
    assert await tts.check() is ServiceStatus.FAIL


async def test_status_becomes_ok_after_warm_up() -> None:
    model = FakeSilero()
    tts = synthesizer(model)
    assert await tts.check() is ServiceStatus.UNKNOWN

    await tts.warm_up()

    assert await tts.check() is ServiceStatus.OK
    assert len(model.calls) == 1


async def test_warm_up_can_be_switched_off() -> None:
    model = FakeSilero()
    tts = synthesizer(model, warm_up_on_startup=False)

    await tts.warm_up()

    assert await tts.check() is ServiceStatus.UNKNOWN


async def test_warm_up_failure_is_not_raised() -> None:
    def broken_loader(_: TextToSpeechSettings) -> SileroModelLike:
        raise OSError("нет сети")

    tts = SileroTextToSpeech(TextToSpeechSettings(_env_file=None), load_model=broken_loader)

    await tts.warm_up()

    assert await tts.check() is ServiceStatus.FAIL


def test_pieces_are_joined_with_pauses() -> None:
    rate = 1_000
    joined = joined_with_pauses([np.ones(100, np.float32), np.ones(200, np.float32)], rate)

    assert joined.size == 300 + int(PAUSE_BETWEEN_CHUNKS_SECONDS * rate)
    assert joined.dtype == np.float32


# --- Файл модели --------------------------------------------------------------------------------

MODEL_BYTES = b"pretend this is a torch package"


@pytest.fixture
def pinned_hash(monkeypatch: pytest.MonkeyPatch) -> str:
    digest = hashlib.sha256(MODEL_BYTES).hexdigest()
    monkeypatch.setattr(silero, "MODEL_SHA256", digest)
    return digest


def fake_download(content: bytes, downloads: list[str]) -> object:
    def download(url: str, target: Path) -> str:
        downloads.append(url)
        target.write_bytes(content)
        return hashlib.sha256(content).hexdigest()

    return download


@pytest.mark.usefixtures("pinned_hash")
def test_model_is_downloaded_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    downloads: list[str] = []
    monkeypatch.setattr(silero, "_download", fake_download(MODEL_BYTES, downloads))

    first = ensure_model_file(tmp_path / "silero")
    second = ensure_model_file(tmp_path / "silero")

    assert first == second
    assert first.read_bytes() == MODEL_BYTES
    assert downloads == [silero.MODEL_URL]
    assert not list(first.parent.glob("*.part"))


@pytest.mark.usefixtures("pinned_hash")
def test_corrupted_model_is_downloaded_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    downloads: list[str] = []
    monkeypatch.setattr(silero, "_download", fake_download(MODEL_BYTES, downloads))
    (tmp_path / silero.MODEL_FILE_NAME).write_bytes(b"truncated")

    path = ensure_model_file(tmp_path)

    assert path.read_bytes() == MODEL_BYTES
    assert len(downloads) == 1


@pytest.mark.usefixtures("pinned_hash")
def test_download_with_wrong_hash_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(silero, "_download", fake_download(b"tampered", []))

    with pytest.raises(ModelChecksumError):
        ensure_model_file(tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_pinned_hash_is_sha256() -> None:
    assert len(silero.MODEL_SHA256) == 64
    assert int(silero.MODEL_SHA256, 16) >= 0
