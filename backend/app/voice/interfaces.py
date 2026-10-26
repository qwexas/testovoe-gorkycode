"""Интерфейсы распознавания (Whisper) и синтеза речи (Silero).

Аудио не сохраняется (Q35): реализации работают только с байтами в памяти.

Ошибки — `DomainError` с кодами из контракта API:
- `audio_unsupported` (415) — формат не удалось декодировать;
- `audio_too_large` (413) — больше `MAX_AUDIO_BYTES` или длиннее `MAX_AUDIO_SECONDS`;
- `stt_unavailable` / `tts_unavailable` (503) — модель не загрузилась или упала.
Пустая речь (тишина, шум) — не ошибка распознавателя: `transcribe` возвращает "",
а бизнес-логика отвечает `speech_not_recognized`.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from app.core.enums import ServiceStatus

MAX_AUDIO_BYTES = 10 * 1024 * 1024
"""Предел размера записи (контракт: ≤ 10 МБ)."""
MAX_AUDIO_SECONDS = 60
"""Предел длительности записи (контракт: ≤ 60 с)."""


@dataclass(frozen=True, slots=True)
class AudioClip:
    """Аудиоданные и их MIME-тип (`audio/webm`, `audio/ogg`, `audio/mp4`, `audio/wav`)."""

    data: bytes
    content_type: str


class SpeechToText(Protocol):
    """Распознавание русской речи."""

    async def transcribe(self, audio: AudioClip) -> str:
        """Текст фразы; пустая строка, если речь не распознана."""
        ...

    async def check(self) -> ServiceStatus:
        """Готова ли модель — для `/api/health` (не грузит модель, если её ещё нет)."""
        ...


class TextToSpeech(Protocol):
    """Синтез русской речи."""

    @property
    def voices(self) -> Sequence[str]:
        """Доступные голоса; первый — голос по умолчанию."""
        ...

    async def synthesize(self, text: str, voice: str | None) -> AudioClip:
        """Озвучка `text` голосом `voice` (по умолчанию — голос из настроек) в OGG/Opus."""
        ...

    async def check(self) -> ServiceStatus:
        """Готова ли модель — для `/api/health`."""
        ...
