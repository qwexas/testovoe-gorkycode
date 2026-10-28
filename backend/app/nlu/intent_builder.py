"""Перевод извлечённого моделью (`Extraction`) в `Intent` из контракта.

Здесь считаются даты и периоды (через `app.nlu.time_resolution`) и раскладываются поля
по действию: у переноса «когда» — новые день и время, а `target_date` и `target_time`
описывают запись там, где она стоит сейчас; у удаления названный день описывает удаляемую
запись и т. д. Остальные команды реплики («…и удали встречу с Петром») попадают
в `Intent.unhandled`: выполняется только первая.
"""

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any

from app.core.enums import EventStatus, EventType
from app.nlu.command_words import creation_over_change, is_generic_title, other_commands
from app.nlu.expressions import TimeExpression
from app.nlu.grounding import (
    names_event_type,
    names_moment,
    names_record_by_pronoun,
    same_record,
    spoken_in,
    user_description,
)
from app.nlu.interfaces import Action, DialogContext, Intent, TargetRef, TimeScope, When
from app.nlu.schema import EventTypeName, Extraction, StatusName
from app.nlu.time_resolution import (
    narrow_to_day_part,
    preserve_leading_zero,
    resolve_period,
    resolve_when,
)
from app.nlu.time_scope import search_time_scope

TRIMMED_PUNCTUATION = " \t\n.,!?;:«»\"'"
SHORT_WORD_LENGTH = 2
"""Предлоги «в», «на», «с» не мешают описанию быть «только типом»: «встреча в 10»."""

EVENT_TYPES = {
    EventTypeName.TASK: EventType.TASK,
    EventTypeName.REMINDER: EventType.REMINDER,
    EventTypeName.MEETING: EventType.MEETING,
}
STATUSES = {StatusName.OPEN: EventStatus.OPEN, StatusName.DONE: EventStatus.DONE}

IntentFields = dict[str, Any]


@dataclass(frozen=True, slots=True)
class _Utterance:
    """Реплика, её разбор моделью и контекст диалога."""

    extraction: Extraction
    text: str
    context: DialogContext


def build_intent(extraction: Extraction, text: str, context: DialogContext) -> Intent:
    """`Intent` по ответу модели; даты считаются от `context.now` (Москва).

    «Поставь встречу…», разобранное моделью как перенос, становится созданием
    (`creation_over_change`).
    """
    extraction = creation_over_change(extraction, text)
    fields_for = _FIELDS_BY_ACTION.get(extraction.action, _no_fields)
    utterance = _Utterance(extraction, text, context)
    return Intent(
        action=extraction.action,
        text=text,
        unhandled=_unhandled(extraction, text),
        **fields_for(utterance),
    )


def _unhandled(extraction: Extraction, text: str) -> str | None:
    """Остальные команды реплики: по глаголам-командам или из `rest`, если он сказан.

    Слова самой реплики надёжнее пересказа модели, поэтому сначала — `other_commands`.
    Название и описание записи первой команды — её содержание, а не следующая команда.
    """
    rest = _clean(extraction.rest)
    if rest is not None and not spoken_in(rest, text):
        rest = None
    record = f"{extraction.title} {extraction.query}"
    return other_commands(text, record) or rest


def _create_fields(utterance: _Utterance) -> IntentFields:
    """Название-заглушка («Встреча» из «поставь встречу на завтра») — не названо."""
    extraction = utterance.extraction
    title = _title(extraction.title)
    return {
        "event_type": _event_type(extraction),
        "title": None if title is None or is_generic_title(title) else title,
        "when": _new_when(utterance),
        "duration_minutes": _positive(extraction.duration_minutes),
    }


def _list_fields(utterance: _Utterance) -> IntentFields:
    """Часть суток сужает день: «что у меня завтра вечером» — завтра с 18:00 до полуночи."""
    extraction = utterance.extraction
    now = utterance.context.now
    period = resolve_period(extraction.date_expression, now)
    return {
        "event_type": _event_type(extraction),
        "period": None
        if period is None
        else narrow_to_day_part(period, extraction.time_expression.day_part, now),
        "status": STATUSES.get(extraction.status),
    }


def _search_fields(utterance: _Utterance) -> IntentFields:
    """Поиск без названного предмета ищет по всей реплике: лишние слова отсечёт поиск.

    Время поиска («была» / «будет») сверяется со словами реплики (`search_time_scope`):
    в длинном контексте модель иногда его теряет.
    """
    extraction = utterance.extraction
    scope = search_time_scope(extraction.time_scope, utterance.text)
    return {
        "event_type": _event_type(extraction),
        "query": _clean(extraction.query) or utterance.text.strip(),
        "time_scope": scope,
        "period": resolve_period(extraction.date_expression, utterance.context.now, scope),
        "status": STATUSES.get(extraction.status),
    }


def _reschedule_fields(utterance: _Utterance) -> IntentFields:
    """Прежние день и время (`target_*`) ищут запись, новые (`date`, `time`) — куда её деть.

    Длительность — новая длительность встречи; не названа — остаётся прежней.
    """
    extraction = utterance.extraction
    record_moment = resolve_when(
        extraction.target_date_expression,
        _with_leading_zero(extraction.target_time_expression, utterance.text),
        utterance.context.now,
        TimeScope.ANY,
    )
    return {
        "target": _target(utterance, record_moment),
        "when": _new_when(utterance),
        "duration_minutes": _positive(extraction.duration_minutes),
    }


def _rename_fields(utterance: _Utterance) -> IntentFields:
    title = _title(utterance.extraction.renamed_to)
    return {"target": _target(utterance, _record_when(utterance), title), "title": title}


def _change_fields(utterance: _Utterance) -> IntentFields:
    """Отметка о выполнении и удаление: названный день описывает саму запись."""
    return {"target": _target(utterance, _record_when(utterance))}


def _answer_fields(utterance: _Utterance) -> IntentFields:
    extraction = utterance.extraction
    return {
        "title": _title(extraction.title),
        "when": _new_when(utterance),
        "duration_minutes": _positive(extraction.duration_minutes),
    }


def _choose_fields(utterance: _Utterance) -> IntentFields:
    return {"choice_index": _positive(utterance.extraction.choice)}


def _no_fields(_utterance: _Utterance) -> IntentFields:
    return {}


_FIELDS_BY_ACTION: dict[Action, Callable[[_Utterance], IntentFields]] = {
    Action.CREATE: _create_fields,
    Action.LIST: _list_fields,
    Action.SEARCH: _search_fields,
    Action.RESCHEDULE: _reschedule_fields,
    Action.RENAME: _rename_fields,
    Action.COMPLETE: _change_fields,
    Action.DELETE: _change_fields,
    Action.ANSWER: _answer_fields,
    Action.CHOOSE: _choose_fields,
}


def _new_when(utterance: _Utterance) -> When | None:
    """Новые день и время: при создании, переносе, ответе на уточнение — только будущие."""
    extraction = utterance.extraction
    return resolve_when(
        extraction.date_expression, _time_expression(utterance), utterance.context.now
    )


def _record_when(utterance: _Utterance) -> When | None:
    """Когда стоит изменяемая запись: «удали встречу в четверг» — ближайший четверг."""
    extraction = utterance.extraction
    return resolve_when(
        extraction.date_expression,
        _time_expression(utterance),
        utterance.context.now,
        TimeScope.ANY,
    )


def _time_expression(utterance: _Utterance) -> TimeExpression:
    """Названное время с ведущим нулём из реплики (`_with_leading_zero`)."""
    return _with_leading_zero(utterance.extraction.time_expression, utterance.text)


def _with_leading_zero(expression: TimeExpression, text: str) -> TimeExpression:
    """Возвращаем ведущий ноль из текста, если извлечение нормализовало «06:30» в «6:30»."""
    return replace(expression, clock=preserve_leading_zero(expression.clock, text))


def _target(utterance: _Utterance, when: When | None, new_title: str | None = None) -> TargetRef:
    """Ссылка на изменяемую запись, сверенная со словами реплики (`app.nlu.grounding`).

    Описание, день и тип записи берутся из ответа модели, только если они есть в самой
    реплике: модель иногда подставляет название, тип и дату записи из фокуса.
    Запись из контекста (`last=True`), если она названа местоимением («перенеси её»), не
    описана вовсе («перенеси на завтра»). Названное описание всегда запускает поиск.
    Запись, описанная только типом и временем («перенеси завтрашнюю встречу в 10 на 12»),
    ищется по дню и времени: `query` пустой, `last=False`, `when` — где она стоит сейчас.
    При переименовании новое название — не описание записи («переименуй её в …»).
    """
    extraction = utterance.extraction
    text = utterance.text
    pronoun = names_record_by_pronoun(text)
    query = None if pronoun else user_description(_clean(extraction.query), text)
    if query is not None and new_title is not None and same_record(query, new_title):
        query = None
    moment = when if names_moment(text) else None
    if query is not None and moment is not None and _names_only_type(query):
        query = None
    by_moment = query is None and moment is not None and not pronoun
    last = query is None and not by_moment
    return TargetRef(
        last=last,
        query=query,
        event_type=_event_type(extraction) if names_event_type(text) else None,
        when=moment,
    )


def _names_only_type(query: str) -> bool:
    """«Встреча», «завтрашняя встреча в 10» — тип и время записи, без её содержания."""
    words = [
        word for word in query.split() if len(word) > SHORT_WORD_LENGTH and not names_moment(word)
    ]
    return not words or is_generic_title(" ".join(words))


def _event_type(extraction: Extraction) -> EventType | None:
    return EVENT_TYPES.get(extraction.event_type)


def _title(raw: str) -> str | None:
    title = _clean(raw)
    return None if title is None else title[0].upper() + title[1:]


def _clean(raw: str) -> str | None:
    cleaned = " ".join(raw.split()).strip(TRIMMED_PUNCTUATION)
    return cleaned or None


def _positive(value: int) -> int | None:
    return value if value > 0 else None
