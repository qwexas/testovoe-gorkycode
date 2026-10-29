"""Распознавание русской речи faster-whisper на CPU, int8, с VAD-фильтром (Q5, Q20).

Запись декодируется в памяти (`app.voice.audio`), модель грузится лениво — при первой
фразе или в `warm_up()` при старте — и работает в отдельном потоке, не блокируя event loop.
Одновременно распознаётся не больше `max_concurrency` фраз, остальные ждут в очереди.
"""

import asyncio
import logging
from collections.abc import Callable, Iterable
from typing import Protocol

import numpy as np
from numpy.typing import NDArray

from app.core.enums import ServiceStatus
from app.core.errors import SpeechToTextUnavailableError
from app.voice.audio import decode_speech
from app.voice.interfaces import AudioClip
from app.voice.lazy_model import LazyModel
from app.voice.settings import SpeechToTextSettings

logger = logging.getLogger(__name__)

DEVICE = "cpu"
COMPUTE_TYPE = "int8"
"""GPU сервера (GTX 960, CC 5.2) не умеет int8/float16 в CTranslate2 — только CPU (Q20)."""
LANGUAGE = "ru"
DOMAIN_PROMPT = "Горький, напомни завтра в 15:00 про созвон. Встреча, задача, напоминание."
"""Подсказка декодеру: имя ассистента, лексика и запись времени цифрами. По замеру
(`scripts/voice_roundtrip.py`) на large-v3-turbo без изменений, на small +2,4 п. п. точных."""


class WhisperSegment(Protocol):
    """Отрезок распознанной речи."""

    @property
    def text(self) -> str:
        """Текст отрезка."""
        ...


class WhisperModelLike(Protocol):
    """То, что нужно от `faster_whisper.WhisperModel`."""

    def transcribe(
        self, audio: NDArray[np.float32], **options: object
    ) -> tuple[Iterable[WhisperSegment], object]:
        """Отрезки (ленивый итератор) и сведения о записи."""
        ...


ModelLoader = Callable[[SpeechToTextSettings], WhisperModelLike]


def load_whisper_model(settings: SpeechToTextSettings) -> WhisperModelLike:
    """Загружает модель (при необходимости скачивает в `cache_dir`); импорт отложен."""
    from faster_whisper import WhisperModel  # type: ignore[import-untyped]

    model: WhisperModelLike = WhisperModel(
        settings.model,
        device=DEVICE,
        compute_type=COMPUTE_TYPE,
        cpu_threads=settings.cpu_threads,
        num_workers=settings.max_concurrency,
        download_root=str(settings.cache_dir) if settings.cache_dir is not None else None,
    )
    return model


class WhisperSpeechToText:
    """Реализация `SpeechToText` на faster-whisper.

    Без аргументов настройки читаются из `STT_*` и корневого `.env`.
    """

    def __init__(
        self,
        settings: SpeechToTextSettings | None = None,
        load_model: ModelLoader = load_whisper_model,
    ) -> None:
        self._settings = settings or SpeechToTextSettings()
        self._model = LazyModel(
            f"faster-whisper {self._settings.model}", lambda: load_model(self._settings)
        )
        self._slots = asyncio.Semaphore(self._settings.max_concurrency)
        self._options: dict[str, object] = {
            "language": LANGUAGE,
            "beam_size": self._settings.beam_size,
            "vad_filter": True,
            "initial_prompt": DOMAIN_PROMPT if self._settings.domain_prompt else None,
            "condition_on_previous_text": False,
            "without_timestamps": True,
        }

    async def warm_up(self) -> None:
        """Загружает модель заранее, если включён `STT_WARM_UP_ON_STARTUP`.

        Холостой прогон не нужен: по замеру первая фраза после загрузки не медленнее
        следующих. Ошибку только пишет в лог: `/api/health` покажет `fail`, а первая
        фраза попробует загрузить модель снова.
        """
        if not self._settings.warm_up_on_startup:
            return
        try:
            await asyncio.to_thread(self._model.get)
        except Exception:
            logger.exception("Модель распознавания речи не загрузилась при старте")

    async def transcribe(self, audio: AudioClip) -> str:
        """Текст фразы; пустая строка, если речи нет (тишина или шум).

        Raises:
            AudioTooLargeError: Запись больше 10 МБ или длиннее 60 с.
            AudioUnsupportedError: Запись не декодируется.
            SpeechToTextUnavailableError: Модель не загрузилась или упала.
        """
        samples = await asyncio.to_thread(decode_speech, audio.data)
        if samples.size == 0:
            return ""
        return await self._in_slot(samples)

    async def _in_slot(self, samples: NDArray[np.float32]) -> str:
        """Распознавание в слоте модели; слот освобождается, когда закончит поток.

        Если запрос отменён (срок хода, обрыв связи), поток Whisper всё равно дорабатывает —
        освобождать слот раньше нельзя, иначе на CPU окажется больше моделей, чем слотов.
        """
        await self._slots.acquire()
        work = asyncio.ensure_future(asyncio.to_thread(self._recognize, samples))
        work.add_done_callback(self._release_slot)
        return await asyncio.shield(work)

    def _release_slot(self, work: "asyncio.Future[str]") -> None:
        self._slots.release()
        if not work.cancelled():
            # Ошибку получает ожидающий запрос; после его отмены — пусть не пишет в лог
            # «exception was never retrieved».
            work.exception()

    async def check(self) -> ServiceStatus:
        """`ok` — модель загружена, `unknown` — ещё не грузилась, `fail` — загрузка упала."""
        return self._model.status

    def _recognize(self, samples: NDArray[np.float32]) -> str:
        try:
            segments, _ = self._model.get().transcribe(samples, **self._options)
            text = " ".join(segment.text.strip() for segment in segments)
        except Exception as error:
            logger.exception("Распознавание речи упало")
            raise SpeechToTextUnavailableError() from error
        return text.strip()
