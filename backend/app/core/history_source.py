"""исходные данные истории из CSV (решение Q22) и правила определения типа записи.

CSV `voice_assistant_events_1000.csv` содержит только дату, время и текст. Тип
определяется по первому слову названия: встреча начинается с названия формата
встречи («Встреча с…», «Созвон с…», «Демо…», «Обсудить…», «Провести планёрку…»).
Слово «встреча» не в начале («Подготовиться к встрече», «Отправить итоги встречи»)
означает задачу. Напоминания из CSV не выделяются: «Напомнить…» — это задача.

Из CSV собирается закоммиченный файл `app/seed/events_seed.json`
(`uv run python -m scripts.build_seed`); приложение читает только его.
"""

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path

from pydantic import TypeAdapter

from app.core.enums import EventType
from app.core.schedule import DEFAULT_MEETING_DURATION, MOSCOW

SEED_FILE = Path(__file__).resolve().parents[1] / "seed" / "events_seed.json"

MEETING_WORD_STEMS = (
    "встреч",
    "созвон",
    "демо",
    "планёрк",
    "планерк",
    "обсуд",
    "обсужд",
    "синк",
    "интервью",
    "совещан",
    "митинг",
    "собеседован",
)
"""начала слов, которыми называют встречу: «встреча», «обсудить», «планёрку»…"""

LEADING_VERBS = frozenset({"провести"})
"""глагол перед названием встречи: «Провести планёрку» — встреча."""

_WORD = re.compile(r"[а-яёa-z0-9]+")


@dataclass(frozen=True, slots=True)
class HistoryEntry:
    """запись истории: строка CSV с определённым типом и временем по Москве."""

    id: int
    type: EventType
    title: str
    starts_at: datetime
    has_time: bool
    ends_at: datetime | None


_ENTRIES = TypeAdapter(list[HistoryEntry])


def classify_event_type(title: str) -> EventType:
    """встреча, если название начинается с формата встречи, иначе задача."""
    words = _WORD.findall(title.lower())
    if words and words[0] in LEADING_VERBS:
        words = words[1:]
    is_meeting = bool(words) and words[0].startswith(MEETING_WORD_STEMS)
    return EventType.MEETING if is_meeting else EventType.TASK


def entry_from_csv_row(row: Mapping[str, str]) -> HistoryEntry:
    """строка CSV (`id`, `date`, `time`, `text`) → запись; дата не сдвигается."""
    title = row["text"].strip()
    event_type = classify_event_type(title)
    starts_at = datetime.combine(
        date.fromisoformat(row["date"]), time.fromisoformat(row["time"]), tzinfo=MOSCOW
    )
    ends_at = starts_at + DEFAULT_MEETING_DURATION if event_type is EventType.MEETING else None
    return HistoryEntry(
        id=int(row["id"]),
        type=event_type,
        title=title,
        starts_at=starts_at,
        has_time=True,
        ends_at=ends_at,
    )


def render_history_file(entries: Sequence[HistoryEntry]) -> str:
    """JSON-массив по записи на строку: так изменения в файле легко читать в diff."""
    items = _ENTRIES.dump_python(list(entries), mode="json")
    lines = ",\n".join(f"  {json.dumps(item, ensure_ascii=False)}" for item in items)
    return f"[\n{lines}\n]\n"


def read_history_file(path: Path = SEED_FILE) -> list[HistoryEntry]:
    """записи истории из JSON-файла с проверкой типов полей."""
    return _ENTRIES.validate_json(path.read_bytes())
