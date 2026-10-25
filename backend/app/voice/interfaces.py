"""Интерфейсы распознавания (Whisper) и синтеза речи (Silero).

Аудио не сохраняется (Q35): реализации работают только с байтами в памяти.
"""

from dataclasses import dataclass
from typing import Protocol


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


class TextToSpeech(Protocol):
    """Синтез русской речи."""

    async def synthesize(self, text: str, voice: str | None) -> AudioClip:
        """Озвучка `text` голосом `voice` (по умолчанию — голос из настроек) в OGG/Opus."""
        ...
