"""Голос в бизнес-логике: распознанная фраза, озвучка, выбор голоса, лимит и сбои моделей."""

import logging
from collections.abc import Sequence
from uuid import uuid4

import pytest

from app.core.enums import ServiceStatus
from app.core.errors import (
    AudioUnsupportedError,
    SpeechNotRecognizedError,
    SpeechToTextUnavailableError,
    TextToSpeechUnavailableError,
    TooManySpeechRequestsError,
    UnknownVoiceError,
)
from app.core.rate_limit import SlidingWindowRateLimiter
from app.core.speech import SpeechSynthesis, SynthesisThrottle, recognize_speech
from app.voice.interfaces import AudioClip

SPEECH = AudioClip(data=b"OggS-secret-voice-bytes", content_type="audio/ogg")
VOICES = ("xenia", "baya", "aidar")


class ScriptedSpeechToText:
    def __init__(self, result: str | Exception) -> None:
        self.result = result
        self.calls = 0

    async def transcribe(self, audio: AudioClip) -> str:
        self.calls += 1
        if isinstance(self.result, Exception):
            raise self.result
        return self.result

    async def check(self) -> ServiceStatus:
        return ServiceStatus.OK


class RecordingTextToSpeech:
    def __init__(self, voices: Sequence[str] = VOICES, failure: Exception | None = None) -> None:
        self._voices = voices
        self._failure = failure
        self.requests: list[tuple[str, str | None]] = []

    @property
    def voices(self) -> Sequence[str]:
        return self._voices

    async def synthesize(self, text: str, voice: str | None) -> AudioClip:
        self.requests.append((text, voice))
        if self._failure is not None:
            raise self._failure
        return AudioClip(data=b"OggS" + text.encode(), content_type="audio/ogg")

    async def check(self) -> ServiceStatus:
        return ServiceStatus.OK


def synthesis(voice: RecordingTextToSpeech, max_hits: int = 1000) -> SpeechSynthesis:
    limiter = SlidingWindowRateLimiter(max_hits=max_hits, window_seconds=60)
    return SpeechSynthesis(voice, SynthesisThrottle(limiter))


class TestRecognizeSpeech:
    async def test_phrase_is_trimmed(self) -> None:
        phrase = await recognize_speech(ScriptedSpeechToText("  Что у меня сегодня?\n"), SPEECH)

        assert phrase == "Что у меня сегодня?"

    @pytest.mark.parametrize("silence", ["", "   ", "\n\t"])
    async def test_silence_is_not_recognized(self, silence: str) -> None:
        with pytest.raises(SpeechNotRecognizedError) as raised:
            await recognize_speech(ScriptedSpeechToText(silence), SPEECH)

        assert raised.value.message == "Не расслышал, повторите, пожалуйста."

    async def test_empty_record_skips_the_model(self) -> None:
        speech = ScriptedSpeechToText("не должно вызываться")

        with pytest.raises(SpeechNotRecognizedError):
            await recognize_speech(speech, AudioClip(data=b"", content_type="audio/webm"))

        assert speech.calls == 0

    async def test_contract_errors_of_the_model_pass_through(self) -> None:
        with pytest.raises(AudioUnsupportedError):
            await recognize_speech(ScriptedSpeechToText(AudioUnsupportedError()), SPEECH)

    async def test_model_crash_is_stt_unavailable_and_audio_is_not_logged(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        crash = ScriptedSpeechToText(RuntimeError("модель упала"))

        with caplog.at_level(logging.ERROR), pytest.raises(SpeechToTextUnavailableError):
            await recognize_speech(crash, SPEECH)

        assert "stt_unavailable" in caplog.text
        assert "secret-voice-bytes" not in caplog.text


class TestSpeechSynthesis:
    async def test_default_voice(self) -> None:
        voice = RecordingTextToSpeech()

        clip = await synthesis(voice).synthesize(uuid4(), "Готово.", None)

        assert (clip.data, clip.content_type) == (b"OggS" + "Готово.".encode(), "audio/ogg")
        assert voice.requests == [("Готово.", None)]

    async def test_chosen_voice(self) -> None:
        voice = RecordingTextToSpeech()

        await synthesis(voice).synthesize(uuid4(), "Готово.", "baya")

        assert voice.requests == [("Готово.", "baya")]

    async def test_unknown_voice_is_validation_error_and_not_counted(self) -> None:
        voice = RecordingTextToSpeech()
        service = synthesis(voice, max_hits=1)
        profile_id = uuid4()

        with pytest.raises(UnknownVoiceError) as raised:
            await service.synthesize(profile_id, "Готово.", "robot")
        await service.synthesize(profile_id, "Готово.", None)

        assert raised.value.code == "validation_error"
        assert raised.value.message == "Такого голоса нет. Доступны: xenia, baya, aidar."
        assert voice.requests == [("Готово.", None)]

    async def test_without_voices_the_synthesizer_reports_unavailability(self) -> None:
        voice = RecordingTextToSpeech(voices=(), failure=TextToSpeechUnavailableError())

        with pytest.raises(TextToSpeechUnavailableError):
            await synthesis(voice).synthesize(uuid4(), "Готово.", "baya")

    async def test_forty_per_minute_per_profile(self) -> None:
        service = SpeechSynthesis(RecordingTextToSpeech(), SynthesisThrottle())
        profile_id = uuid4()
        for _ in range(40):
            await service.synthesize(profile_id, "Готово.", None)

        with pytest.raises(TooManySpeechRequestsError) as raised:
            await service.synthesize(profile_id, "Готово.", None)
        await service.synthesize(uuid4(), "Другой профиль.", None)

        assert raised.value.retry_after_seconds == 60
        assert raised.value.code == "rate_limited"

    async def test_model_crash_is_tts_unavailable(self) -> None:
        voice = RecordingTextToSpeech(failure=RuntimeError("модель упала"))

        with pytest.raises(TextToSpeechUnavailableError) as raised:
            await synthesis(voice).synthesize(uuid4(), "Готово.", None)

        assert raised.value.code == "tts_unavailable"
