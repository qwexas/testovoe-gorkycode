"""Перевод извлечённого моделью (`Extraction`) в `Intent` из контракта.

Здесь считаются даты и периоды (через `app.nlu.time_resolution`) и раскладываются поля
по действию: у переноса «когда» — новое время, а день из `target_date` описывает запись;
у удаления названный день описывает удаляемую запись и т. д.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.core.enums import EventStatus, EventType
from app.nlu.expressions import TimeExpression
from app.nlu.interfaces import Action, DialogContext, Intent, TargetRef, TimeScope, When
from app.nlu.schema import EventTypeName, Extraction, StatusName
from app.nlu.time_resolution import resolve_period, resolve_when

TRIMMED_PUNCTUATION = " \t\n.,!?;:«»\"'"

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
    """`Intent` по ответу модели; даты считаются от `context.now` (Москва)."""
    fields_for = _FIELDS_BY_ACTION.get(extraction.action, _no_fields)
    utterance = _Utterance(extraction, text, context)
    return Intent(action=extraction.action, text=text, **fields_for(utterance))


def _create_fields(utterance: _Utterance) -> IntentFields:
    extraction = utterance.extraction
    return {
        "event_type": _event_type(extraction),
        "title": _title(extraction.title),
        "when": _new_when(utterance),
        "duration_minutes": _positive(extraction.duration_minutes),
    }


def _list_fields(utterance: _Utterance) -> IntentFields:
    extraction = utterance.extraction
    return {
        "event_type": _event_type(extraction),
        "period": resolve_period(extraction.date_expression, utterance.context.now),
        "status": STATUSES.get(extraction.status),
    }


def _search_fields(utterance: _Utterance) -> IntentFields:
    """Поиск без названного предмета ищет по всей реплике: лишние слова отсечёт поиск."""
    extraction = utterance.extraction
    scope = extraction.time_scope
    return {
        "event_type": _event_type(extraction),
        "query": _clean(extraction.query) or utterance.text.strip(),
        "time_scope": scope,
        "period": resolve_period(extraction.date_expression, utterance.context.now, scope),
        "status": STATUSES.get(extraction.status),
    }


def _reschedule_fields(utterance: _Utterance) -> IntentFields:
    extraction = utterance.extraction
    record_day = resolve_when(
        extraction.target_date_expression, TimeExpression(), utterance.context.now, TimeScope.ANY
    )
    return {
        "target": _target(utterance, record_day),
        "when": _new_when(utterance),
        "duration_minutes": _positive(extraction.duration_minutes),
    }


def _rename_fields(utterance: _Utterance) -> IntentFields:
    return {
        "target": _target(utterance, _record_when(utterance)),
        "title": _title(utterance.extraction.renamed_to),
    }


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
        extraction.date_expression, extraction.time_expression, utterance.context.now
    )


def _record_when(utterance: _Utterance) -> When | None:
    """Когда стоит изменяемая запись: «удали встречу в четверг» — ближайший четверг."""
    extraction = utterance.extraction
    return resolve_when(
        extraction.date_expression,
        extraction.time_expression,
        utterance.context.now,
        TimeScope.ANY,
    )


def _target(utterance: _Utterance, when: When | None) -> TargetRef:
    """Ссылка на изменяемую запись.

    Запись из контекста (`last=True`), если она названа местоимением, не описана вовсе
    («перенеси на завтра») или модель описала её названием записи в фокусе — так модель
    иногда «разворачивает» местоимение «её».
    """
    extraction = utterance.extraction
    query = _clean(extraction.query)
    last = extraction.about_last or query is None or _names_focus(query, utterance.context)
    return TargetRef(last=last, query=query, event_type=_event_type(extraction), when=when)


def _names_focus(query: str, context: DialogContext) -> bool:
    return bool(context.focus) and _normalized(query) == _normalized(context.focus[0].title)


def _normalized(text: str) -> str:
    return " ".join(text.lower().replace("ё", "е").split()).strip(TRIMMED_PUNCTUATION)


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
