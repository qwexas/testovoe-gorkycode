"""синтез русской речи Silero v4_ru на CPU (Q13): текст → слова → Silero → OGG/Opus.

Файл модели скачивается один раз с models.silero.ai в кэш и сверяется с SHA-256: загрузка
`torch.package` исполняет код из файла, поэтому чужой или битый файл не грузим.
Лицензия Silero — некоммерческая (CC BY-NC-SA 4.0); владелец проекта это принял (Q13).
"""

import asyncio
import hashlib
import logging
import os
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Protocol

import httpx
import numpy as np
from numpy.typing import NDArray

from app.core.enums import ServiceStatus
from app.core.errors import TextToSpeechUnavailableError, UnknownVoiceError
from app.voice.audio import OGG_CONTENT_TYPE, encode_ogg_opus
from app.voice.interfaces import AudioClip
from app.voice.lazy_model import LazyModel
from app.voice.settings import SILERO_VOICES, TextToSpeechSettings
from app.voice.text_normalizer import normalize_for_speech, speech_chunks

logger = logging.getLogger(__name__)

MODEL_URL = "https://models.silero.ai/models/tts/ru/v4_ru.pt"
MODEL_SHA256 = "896ab96347d5bd781ab97959d4fd6885620e5aab52405d3445626eb7c1414b00"
MODEL_FILE_NAME = "v4_ru.pt"
DOWNLOAD_TIMEOUT_SECONDS = 120.0
DOWNLOAD_CHUNK_BYTES = 1 << 20
PAUSE_BETWEEN_CHUNKS_SECONDS = 0.25
EMPTY_SPEECH_SECONDS = 0.3
"""если озвучивать нечего (одни эмодзи), отдаём короткую тишину — клиенту не нужен особый случай."""
WARM_UP_TEXT = "Горький на связи."


class ModelChecksumError(RuntimeError):
    """скачанный файл модели не совпал с ожидаемым SHA-256."""


class SpeechTensor(Protocol):
    """результат `apply_tts` — тензор torch с сигналом в [-1, 1]."""

    def numpy(self) -> NDArray[np.float32]:
        """сигнал как массив numpy."""
        ...


class SileroModelLike(Protocol):
    """то, что нужно от модели Silero."""

    def apply_tts(
        self, *, text: str, speaker: str, sample_rate: int, put_accent: bool, put_yo: bool
    ) -> SpeechTensor:
        """озвучка `text` голосом `speaker`."""
        ...


ModelLoader = Callable[[TextToSpeechSettings], SileroModelLike]


def ensure_model_file(directory: Path) -> Path:
    """путь к проверенному файлу модели; скачивает его, если файла нет или он битый.

    Raises:
        ModelChecksumError: Скачанный файл не совпал с `MODEL_SHA256`.
        httpx.HTTPError: Не удалось скачать.
    """
    path = directory / MODEL_FILE_NAME
    if path.is_file() and _sha256_of(path) == MODEL_SHA256:
        return path
    directory.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(".part")
    logger.info("Скачиваю модель Silero %s в %s", MODEL_URL, directory)
    try:
        digest = _download(MODEL_URL, partial)
        if digest != MODEL_SHA256:
            raise ModelChecksumError(
                f"SHA-256 файла {MODEL_URL} — {digest}, ожидался {MODEL_SHA256}"
            )
        os.replace(partial, path)
    finally:
        partial.unlink(missing_ok=True)
    return path


def _sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(DOWNLOAD_CHUNK_BYTES), b""):
            digest.update(block)
    return digest.hexdigest()


def _download(url: str, target: Path) -> str:
    """скачивает `url` в `target` и возвращает SHA-256 скачанного."""
    digest = hashlib.sha256()
    with (
        httpx.stream("GET", url, timeout=DOWNLOAD_TIMEOUT_SECONDS, follow_redirects=True) as reply,
        target.open("wb") as file,
    ):
        reply.raise_for_status()
        for block in reply.iter_bytes(DOWNLOAD_CHUNK_BYTES):
            digest.update(block)
            file.write(block)
    return digest.hexdigest()


def default_model_directory() -> Path:
    """`TORCH_HOME/hub/silero` — в Docker это том `/models`."""
    import torch

    return Path(torch.hub.get_dir()) / "silero"


def load_silero_model(settings: TextToSpeechSettings) -> SileroModelLike:
    """скачивает (при необходимости), проверяет и загружает модель на CPU; импорт torch отложен."""
    import torch
    from torch.package.package_importer import PackageImporter

    path = ensure_model_file(settings.cache_dir or default_model_directory())
    package_model = PackageImporter(str(path)).load_pickle("tts_models", "model")
    package_model.to(torch.device("cpu"))
    model: SileroModelLike = package_model
    return model


class SileroTextToSpeech:
    """реализация `TextToSpeech` на Silero v4_ru.

    Без аргументов настройки читаются из `TTS_*` и корневого `.env`.
    Озвучки идут по одной: каждая занимает все ядра torch, параллельно было бы не быстрее.
    """

    def __init__(
        self,
        settings: TextToSpeechSettings | None = None,
        load_model: ModelLoader = load_silero_model,
    ) -> None:
        self._settings = settings or TextToSpeechSettings()
        self._model = LazyModel("Silero v4_ru", lambda: load_model(self._settings))
        default_voice = self._settings.voice
        self._voices = (default_voice, *(name for name in SILERO_VOICES if name != default_voice))
        self._turn = asyncio.Lock()

    @property
    def voices(self) -> Sequence[str]:
        """голоса Silero (Q38); первый — голос по умолчанию из `TTS_VOICE`."""
        return self._voices

    async def warm_up(self) -> None:
        """загружает модель и озвучивает короткую фразу, если включён `TTS_WARM_UP_ON_STARTUP`.

        Ошибку только пишет в лог: `/api/health` покажет `fail`, а первая озвучка
        попробует загрузить модель снова.
        """
        if not self._settings.warm_up_on_startup:
            return
        try:
            async with self._turn:
                await asyncio.to_thread(self._render, WARM_UP_TEXT, self._settings.voice)
        except TextToSpeechUnavailableError:
            logger.warning("Озвучка не прогрелась при старте: /api/health покажет fail")
        except Exception:
            logger.exception("Прогрев озвучки упал")

    async def synthesize(self, text: str, voice: str | None) -> AudioClip:
        """озвучка `text` в OGG/Opus; числа, даты и латиница читаются словами.

        Raises:
            UnknownVoiceError: Такого голоса нет.
            TextToSpeechUnavailableError: Модель не загрузилась или упала.
        """
        speaker = voice or self._settings.voice
        if speaker not in self._voices:
            raise UnknownVoiceError(f"Такого голоса нет. Доступны: {', '.join(self._voices)}.")
        async with self._turn:
            data = await asyncio.to_thread(self._render, text, speaker)
        return AudioClip(data=data, content_type=OGG_CONTENT_TYPE)

    async def check(self) -> ServiceStatus:
        """`ok` — модель загружена, `unknown` — ещё не грузилась, `fail` — загрузка упала."""
        return self._model.status

    def _render(self, text: str, speaker: str) -> bytes:
        chunks = speech_chunks(normalize_for_speech(text))
        sample_rate = self._settings.sample_rate
        pieces = self._spoken(chunks, speaker) if chunks else []
        return encode_ogg_opus(joined_with_pauses(pieces, sample_rate), sample_rate)

    def _spoken(self, chunks: Sequence[str], speaker: str) -> list[NDArray[np.float32]]:
        try:
            model = self._model.get()
            return [
                model.apply_tts(
                    text=chunk,
                    speaker=speaker,
                    sample_rate=self._settings.sample_rate,
                    put_accent=True,
                    put_yo=True,
                ).numpy()
                for chunk in chunks
            ]
        except Exception as error:
            logger.exception("Синтез речи упал")
            raise TextToSpeechUnavailableError() from error


def joined_with_pauses(
    pieces: Sequence[NDArray[np.float32]], sample_rate: int
) -> NDArray[np.float32]:
    """куски речи через короткие паузы; без кусков — короткая тишина."""
    if not pieces:
        return np.zeros(int(EMPTY_SPEECH_SECONDS * sample_rate), dtype=np.float32)
    pause = np.zeros(int(PAUSE_BETWEEN_CHUNKS_SECONDS * sample_rate), dtype=np.float32)
    joined: list[NDArray[np.float32]] = []
    for piece in pieces:
        if joined:
            joined.append(pause)
        joined.append(piece.astype(np.float32, copy=False))
    return np.concatenate(joined)
