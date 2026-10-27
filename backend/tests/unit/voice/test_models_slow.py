"""Настоящие Silero и Whisper: озвучка → распознавание. Медленно, только с GORKY_RUN_SLOW=1."""

import numpy as np
import pytest

from app.core.enums import ServiceStatus
from app.voice.audio import SPEECH_SAMPLE_RATE, decode_speech, encode_ogg_opus
from app.voice.interfaces import AudioClip
from app.voice.settings import SILERO_VOICES, SpeechToTextSettings, TextToSpeechSettings
from app.voice.silero import SileroTextToSpeech
from app.voice.whisper import WhisperSpeechToText
from scripts.voice_roundtrip import MODELS_DIR, comparable

pytestmark = pytest.mark.slow

PHRASE = "Добавь встречу с командой завтра в 15:00"
MIN_SPEECH_SECONDS = 1.0


@pytest.fixture(scope="module")
def tts() -> SileroTextToSpeech:
    return SileroTextToSpeech(TextToSpeechSettings(_env_file=None, cache_dir=MODELS_DIR / "silero"))


@pytest.fixture(scope="module")
def stt() -> WhisperSpeechToText:
    return WhisperSpeechToText(SpeechToTextSettings(_env_file=None, cache_dir=MODELS_DIR))


@pytest.mark.parametrize("voice", SILERO_VOICES)
async def test_every_voice_speaks(tts: SileroTextToSpeech, voice: str) -> None:
    clip = await tts.synthesize("Сегодня у вас 2 задачи.", voice)

    assert decode_speech(clip.data).size / SPEECH_SAMPLE_RATE > MIN_SPEECH_SECONDS
    assert await tts.check() is ServiceStatus.OK


async def test_spoken_phrase_is_recognized(
    tts: SileroTextToSpeech, stt: WhisperSpeechToText
) -> None:
    clip = await tts.synthesize(PHRASE, "xenia")

    heard = await stt.transcribe(clip)

    assert comparable(heard) == comparable(PHRASE)
    assert await stt.check() is ServiceStatus.OK


async def test_silence_is_not_speech(stt: WhisperSpeechToText) -> None:
    silence = encode_ogg_opus(np.zeros(3 * 48_000, dtype=np.float32), 48_000)

    assert await stt.transcribe(AudioClip(silence, "audio/ogg")) == ""
