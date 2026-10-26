"""Какие найденные записи считать одинаково подходящими и в каком порядке их называть.

- Оценки близких названий почти равны («Созвон с Орбитой по интеграции / по аналитике»):
  всё, что отстаёт от лучшей оценки не больше `SCORE_MARGIN`, — равноправные кандидаты.
- Пользователь говорит «задача» и о напоминаниях: напоминание для него — вид задачи (ТЗ:
  «Создание задачи / напоминания»). Поэтому «какие задачи на завтра?» показывает и их.
- Среди равных по оценке записей первой называется ближайшая будущая, затем самая свежая
  прошедшая, записи без даты — в конце.
"""

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from types import MappingProxyType
from typing import Final

from app.core.enums import EventType
from app.core.events import EventCard, ScoredCard

SCORE_MARGIN = 0.06
"""Насколько оценка записи может отставать от лучшей, чтобы считаться равноправным кандидатом.

Меньше бонуса за тип из разбора (0,075): «Отправить итоги встречи Иваном» не встанет рядом
со встречами на «когда была встреча с Иваном». И больше разброса оценок одинаковых по смыслу
названий: «Позвонить Ивану» не потеряет повтор с чуть другим вектором.
"""
WHEN_SCORE_MARGIN = 0.10
"""Шире `SCORE_MARGIN` — для вопросов «когда была / будет …».

Здесь важно совпадение сути (встреча + Иван), а не темы: на «следующая встреча с Иваном»
«Встреча с Иваном по бюджету» отстаёт от «…по презентации» на 0,072 и должна остаться
кандидатом, а «Отправить итоги встречи Иваном» (отставание 0,145) — нет. Замер на CSV 26.10.
"""
SCORE_DIGITS = 6
"""Оценки, равные до этого знака, — одинаковые (повторы одного названия)."""

ASKED_TYPES: Final[Mapping[EventType, frozenset[EventType]]] = MappingProxyType(
    {
        EventType.TASK: frozenset({EventType.TASK, EventType.REMINDER}),
        EventType.REMINDER: frozenset({EventType.REMINDER}),
        EventType.MEETING: frozenset({EventType.MEETING}),
    }
)
"""Какие записи подходят под тип, названный пользователем: «задачи» — задачи и напоминания."""

_FUTURE, _PAST, _UNDATED = 0, 1, 2


def asked_types(event_type: EventType | None) -> frozenset[EventType] | None:
    """Типы записей для названного типа; `None` — тип не назван, подходят любые."""
    return None if event_type is None else ASKED_TYPES[event_type]


def near_best(found: Sequence[ScoredCard], margin: float = SCORE_MARGIN) -> list[ScoredCard]:
    """Записи, отстающие от лучшей (первой) не больше чем на `margin`."""
    if not found:
        return []
    best = found[0].score
    return [item for item in found if best - item.score <= margin]


def timeliness(card: EventCard, now: datetime) -> tuple[int, timedelta]:
    """Ключ порядка «ближайшая будущая, затем свежая прошедшая, затем без даты»."""
    if card.starts_at is None:
        return _UNDATED, timedelta(0)
    if card.starts_at >= now:
        return _FUTURE, card.starts_at - now
    return _PAST, now - card.starts_at


def by_score_then_timeliness(found: Sequence[ScoredCard], now: datetime) -> list[ScoredCard]:
    """По убыванию оценки; при равной оценке — по `timeliness`."""
    return sorted(
        found, key=lambda item: (-round(item.score, SCORE_DIGITS), timeliness(item.card, now))
    )


def by_date(cards: Sequence[EventCard]) -> list[EventCard]:
    """По времени начала; записи без даты — в конце."""
    return sorted(cards, key=lambda card: (card.starts_at is None, card.starts_at or datetime.min))
