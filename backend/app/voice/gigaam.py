"""распознавание русской речи GigaAM-v3 (SberDevices) через onnx-asr на CPU, int8.

Записи длиннее `DIRECT_SECONDS` режутся по паузам Silero VAD:
модель принимает фрагменты до ~25 с. Загрузка ленивая, распознавание — в отдельном потоке.
"""

import asyncio
import logging
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast

import numpy as np
from numpy.typing import NDArray

from app.core.enums import ServiceStatus
from app.core.errors import SpeechToTextUnavailableError
from app.voice.audio import SPEECH_SAMPLE_RATE, decode_speech
from app.voice.interfaces import AudioClip
from app.voice.lazy_model import LazyModel
from app.voice.settings import SpeechToTextSettings

logger = logging.getLogger(__name__)

QUANTIZATION = "int8"
VAD_MODEL = "silero"
VAD_DIR = "silero-vad"
DIRECT_SECONDS = 20.0
"""короче — целиком одним проходом; длиннее — фрагментами по паузам."""
_SPEECH_PATTERN = re.compile(r"\w")
"""на шуме модель иногда возвращает одну точку — это не речь."""


class AsrSegment(Protocol):
    """фрагмент распознанной речи из onnx-asr с VAD."""

    @property
    def text(self) -> str:
        """текст фрагмента."""
        ...


class AsrModelLike(Protocol):
    """то, что нужно от модели onnx-asr."""

    def recognize(self, waveform: NDArray[np.float32], *, sample_rate: int) -> str:
        """текст записи."""
        ...


class SegmentedAsrLike(Protocol):
    """модель onnx-asr с VAD: запись → фрагменты речи."""

    def recognize(self, waveform: NDArray[np.float32], *, sample_rate: int) -> Iterable[AsrSegment]:
        """фрагменты речи по порядку."""
        ...


@dataclass(frozen=True, slots=True)
class GigaAMModels:
    """модель целиком и та же модель с нарезкой по VAD (для длинных записей)."""

    whole: AsrModelLike
    segmented: Callable[[], SegmentedAsrLike]
    """грузит VAD при первом вызове."""


ModelLoader = Callable[[SpeechToTextSettings], GigaAMModels]


def load_gigaam_models(settings: SpeechToTextSettings) -> GigaAMModels:
    """загружает GigaAM (при необходимости скачивает в `cache_dir/<модель>`); импорт отложен.

    VAD грузится только при первой длинной записи.
    """
    import onnx_asr  # type: ignore[import-untyped,unused-ignore]
    import onnxruntime  # type: ignore[import-untyped,unused-ignore]

    options = onnxruntime.SessionOptions()
    if settings.cpu_threads:
        options.intra_op_num_threads = settings.cpu_threads
    model = onnx_asr.load_model(
        settings.gigaam_model,
        _model_dir(settings, settings.gigaam_model),
        quantization=QUANTIZATION,
        sess_options=options,
    )
    vad: LazyModel[SegmentedAsrLike] = LazyModel(
        "Silero VAD",
        lambda: cast(
            SegmentedAsrLike,
            model.with_vad(onnx_asr.load_vad(VAD_MODEL, _model_dir(settings, VAD_DIR))),
        ),
    )
    return GigaAMModels(cast(AsrModelLike, model), vad.get)


def _model_dir(settings: SpeechToTextSettings, name: str) -> Path | None:
    return settings.cache_dir / name if settings.cache_dir is not None else None


class GigaAMSpeechToText:
    """реализация `SpeechToText` на GigaAM-v3.

    Без аргументов настройки читаются из `STT_*` и корневого `.env`.
    """

    def __init__(
        self,
        settings: SpeechToTextSettings | None = None,
        load_model: ModelLoader = load_gigaam_models,
    ) -> None:
        self._settings = settings or SpeechToTextSettings()
        self._model = LazyModel(
            f"GigaAM {self._settings.gigaam_model}", lambda: load_model(self._settings)
        )
        self._slots = asyncio.Semaphore(self._settings.max_concurrency)

    async def warm_up(self) -> None:
        """загружает модель заранее, если включён `STT_WARM_UP_ON_STARTUP`; ошибку — в лог."""
        if not self._settings.warm_up_on_startup:
            return
        try:
            await asyncio.to_thread(self._model.get)
        except Exception:
            logger.exception("Модель распознавания речи не загрузилась при старте")

    async def transcribe(self, audio: AudioClip) -> str:
        """текст фразы; пустая строка, если речи нет (тишина или шум).

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
        """распознавание в слоте модели; слот освобождается, когда закончит поток.

        Если запрос отменён (срок хода, обрыв связи), поток всё равно дорабатывает —
        освобождать слот раньше нельзя, иначе на CPU окажется больше моделей, чем слотов.
        """
        await self._slots.acquire()
        work = asyncio.ensure_future(asyncio.to_thread(self._recognize, samples))
        work.add_done_callback(self._release_slot)
        return await asyncio.shield(work)

    def _release_slot(self, work: "asyncio.Future[str]") -> None:
        self._slots.release()
        if not work.cancelled():
            # ошибку получает ожидающий запрос; после его отмены — пусть не пишет в лог
            # «exception was never retrieved».
            work.exception()

    async def check(self) -> ServiceStatus:
        """`ok` — модель загружена, `unknown` — ещё не грузилась, `fail` — загрузка упала."""
        return self._model.status

    def _recognize(self, samples: NDArray[np.float32]) -> str:
        try:
            models = self._model.get()
            if samples.size <= DIRECT_SECONDS * SPEECH_SAMPLE_RATE:
                text = models.whole.recognize(samples, sample_rate=SPEECH_SAMPLE_RATE)
            else:
                segments = models.segmented().recognize(samples, sample_rate=SPEECH_SAMPLE_RATE)
                text = " ".join(segment.text.strip() for segment in segments)
        except Exception as error:
            logger.exception("Распознавание речи упало")
            raise SpeechToTextUnavailableError() from error
        text = text.strip()
        return text if _SPEECH_PATTERN.search(text) else ""
