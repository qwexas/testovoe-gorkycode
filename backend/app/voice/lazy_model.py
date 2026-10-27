"""Ленивая загрузка модели речи и её состояние для `/api/health`."""

import logging
import threading
from collections.abc import Callable
from enum import Enum

from app.core.enums import ServiceStatus

logger = logging.getLogger(__name__)


class _LoadState(Enum):
    NOT_LOADED = "not_loaded"
    LOADED = "loaded"
    FAILED = "failed"


_STATUS_BY_STATE = {
    _LoadState.NOT_LOADED: ServiceStatus.UNKNOWN,
    _LoadState.LOADED: ServiceStatus.OK,
    _LoadState.FAILED: ServiceStatus.FAIL,
}


class LazyModel[ModelT]:
    """Модель, которая грузится при первом обращении — один раз, даже из нескольких потоков.

    Если загрузка упала, состояние — `fail`, а следующее обращение пробует снова:
    например, сеть вернулась и веса докачаются.
    """

    def __init__(self, name: str, load: Callable[[], ModelT]) -> None:
        self._name = name
        self._load = load
        self._model: ModelT | None = None
        self._state = _LoadState.NOT_LOADED
        self._lock = threading.Lock()

    @property
    def status(self) -> ServiceStatus:
        """`unknown` — ещё не грузилась, `ok` — загружена, `fail` — загрузка упала."""
        return _STATUS_BY_STATE[self._state]

    def get(self) -> ModelT:
        """Загруженная модель; ошибку загрузки пробрасывает, отметив состояние `fail`."""
        with self._lock:
            if self._model is None:
                self._model = self._loaded()
            return self._model

    def _loaded(self) -> ModelT:
        logger.info("Загружаю модель %s", self._name)
        try:
            model = self._load()
        except Exception:
            self._state = _LoadState.FAILED
            raise
        self._state = _LoadState.LOADED
        return model
