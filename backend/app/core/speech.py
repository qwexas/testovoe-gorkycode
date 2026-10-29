"""Голос в бизнес-логике: распознанная реплика и озвучка ответа.

Модели речи спрятаны за интерфейсами `SpeechToText` и `TextToSpeech` (`app.voice`).
Аудио живёт только в памяти запроса: его не сохраняют и не пишут в лог (Q35).
Неожиданный сбой модели превращается в ошибку контракта `stt_unavailable` /
`tts_unavailable`, ошибки с кодом контракта от самой модели проходят как есть.
"""

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID

from app.core.admission import LOCAL_CLIENT, SpeechAdmission
from app.core.errors import (
    DomainError,
    SpeechNotRecognizedError,
    SpeechToTextUnavailableError,
    TextToSpeechUnavailableError,
    TooManySpeechRequestsError,
    UnknownVoiceError,
)
from app.core.rate_limit import Throttle
from app.voice.interfaces import AudioClip, SpeechToText, TextToSpeech

SYNTHESES_PER_WINDOW = 40
SYNTHESIS_WINDOW_SECONDS = 60

logger = logging.getLogger(__name__)


async def recognize_speech(speech: SpeechToText, audio: AudioClip) -> str:
    """Текст фразы без пробелов по краям.

    Raises:
        SpeechNotRecognizedError: Запись пустая или речи в ней нет.
        DomainError: Запись не подходит (`audio_unsupported`, `audio_too_large`)
            или распознавание недоступно (`stt_unavailable`).
    """
    if not audio.data:
        raise SpeechNotRecognizedError()
    with _model_failure_as(SpeechToTextUnavailableError):
        text = await speech.transcribe(audio)
    phrase = text.strip()
    if not phrase:
        raise SpeechNotRecognizedError()
    return phrase


class SynthesisThrottle(Throttle):
    """Не больше `SYNTHESES_PER_WINDOW` озвучек в минуту на профиль."""

    max_hits = SYNTHESES_PER_WINDOW
    window_seconds = SYNTHESIS_WINDOW_SECONDS
    rejection = TooManySpeechRequestsError


class SpeechSynthesis:
    """Озвучка ответов ассистента с проверкой голоса и лимитами на профиль, IP и очередь."""

    def __init__(
        self,
        synthesizer: TextToSpeech,
        throttle: SynthesisThrottle,
        admission: SpeechAdmission | None = None,
    ) -> None:
        self._synthesizer = synthesizer
        self._throttle = throttle
        self._admission = admission or SpeechAdmission()

    async def synthesize(
        self, profile_id: UUID, text: str, voice_name: str | None, client: str = LOCAL_CLIENT
    ) -> AudioClip:
        """Аудио OGG/Opus с текстом `text`; `voice_name=None` — голос по умолчанию.

        Raises:
            UnknownVoiceError: Такого голоса у синтезатора нет.
            TooManySpeechRequestsError: Профиль превысил лимит озвучек в минуту.
            ServiceBusyError: Лимит IP или общей очереди озвучки.
            TextToSpeechUnavailableError: Модель не загрузилась или упала.
        """
        self._check_voice(voice_name)
        self._throttle.admit(profile_id)
        with self._admission.enter(client), _model_failure_as(TextToSpeechUnavailableError):
            return await self._synthesizer.synthesize(text, voice_name)

    def _check_voice(self, voice_name: str | None) -> None:
        """Голос должен быть из списка синтезатора.

        Пустой список значит, что синтезатор не готов: голос не проверяем, а сам
        синтез ответит `tts_unavailable` — это честнее, чем «нет такого голоса».
        """
        available = self._synthesizer.voices
        if voice_name is None or not available or voice_name in available:
            return
        raise UnknownVoiceError(f"Такого голоса нет. Доступны: {', '.join(available)}.")


@contextmanager
def _model_failure_as(unavailable: type[DomainError]) -> Iterator[None]:
    """Неожиданный сбой модели речи → ошибка контракта `unavailable` (503)."""
    try:
        yield
    except DomainError:
        raise
    except Exception as error:
        logger.exception("Модель речи упала: отвечаем %s", unavailable.code)
        raise unavailable() from error
