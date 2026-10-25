"""Ограничение частоты событий по ключу (IP, профиль) в памяти процесса."""

import math
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

Clock = Callable[[], float]

MAX_TRACKED_KEYS = 10_000


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    """Итог проверки лимита: пропустить или подождать `retry_after_seconds`."""

    allowed: bool
    retry_after_seconds: int = 0


class SlidingWindowRateLimiter:
    """Не больше `max_hits` событий за `window_seconds` на один ключ.

    Отклонённые попытки не учитываются, поэтому блокировка не продлевается
    повторными запросами. Состояние живёт в памяти одного процесса — для
    одного инстанса бэкенда этого достаточно.
    """

    def __init__(self, max_hits: int, window_seconds: float, clock: Clock = time.monotonic) -> None:
        if max_hits < 1 or window_seconds <= 0:
            raise ValueError("Лимит и окно должны быть положительными")
        self._max_hits = max_hits
        self._window_seconds = window_seconds
        self._clock = clock
        self._hits: dict[str, deque[float]] = {}

    def hit(self, key: str) -> RateLimitDecision:
        """Учитывает событие для `key`, если лимит ещё не исчерпан."""
        now = self._clock()
        self._forget_idle_keys(now)
        hits = self._recent_hits(key, now)
        if len(hits) >= self._max_hits:
            wait_seconds = hits[0] + self._window_seconds - now
            return RateLimitDecision(
                allowed=False, retry_after_seconds=max(1, math.ceil(wait_seconds))
            )
        hits.append(now)
        return RateLimitDecision(allowed=True)

    def _recent_hits(self, key: str, now: float) -> deque[float]:
        hits = self._hits.setdefault(key, deque())
        window_start = now - self._window_seconds
        while hits and hits[0] <= window_start:
            hits.popleft()
        return hits

    def _forget_idle_keys(self, now: float) -> None:
        if len(self._hits) < MAX_TRACKED_KEYS:
            return
        window_start = now - self._window_seconds
        idle_keys = [
            key for key, hits in self._hits.items() if not hits or hits[-1] <= window_start
        ]
        for key in idle_keys:
            del self._hits[key]
