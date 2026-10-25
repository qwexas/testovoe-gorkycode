"""История из CSV: правила типа записи, время по Москве и закоммиченный seed-файл."""

from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app.core.enums import EventType
from app.core.history_source import (
    SEED_FILE,
    classify_event_type,
    entry_from_csv_row,
    read_history_file,
    render_history_file,
)
from app.core.schedule import MOSCOW
from scripts.build_seed import CSV_FILE, read_csv_entries

CSV_ROWS = 1000


@pytest.mark.parametrize(
    "title",
    [
        "Встреча с Иваном по презентации",
        "Созвон с Альфой по CRM",
        "Демо проекта по сайту",
        "Провести планёрку по бюджету",
        "Провести планерку по бюджету",
        "Обсудить договору с Алексеем",
        "Обсудить бюджет по CRM",
        "Обсуждение релиза",
        "Синк с командой",
        "Интервью с кандидатом",
        "Совещание отдела",
        "Собеседование с дизайнером",
        "  встреча  с командой",
    ],
)
def test_meeting_formats_are_meetings(title: str) -> None:
    assert classify_event_type(title) is EventType.MEETING


@pytest.mark.parametrize(
    "title",
    [
        "Подготовиться к встрече с Вектором",
        "Отправить итоги встречи Марией",
        "Напомнить Анной про CRM",
        "Позвонить Ивану",
        "Согласовать договор с Ольгой",
        "Собрать обратную связь по сайту",
        "Проверить сроки по хакатону",
        "Провести ревью кода",
        "Провести",
        "",
        "!!!",
    ],
)
def test_other_titles_are_tasks(title: str) -> None:
    assert classify_event_type(title) is EventType.TASK


def test_csv_row_keeps_date_and_time_in_moscow() -> None:
    entry = entry_from_csv_row(
        {"id": "7", "date": "2024-03-01", "time": "09:15", "text": " Подготовить отчёт "}
    )

    assert entry.id == 7
    assert entry.type is EventType.TASK
    assert entry.title == "Подготовить отчёт"
    assert entry.starts_at == datetime(2024, 3, 1, 9, 15, tzinfo=MOSCOW)
    assert entry.starts_at.isoformat() == "2024-03-01T09:15:00+03:00"
    assert entry.has_time is True
    assert entry.ends_at is None


def test_csv_meeting_lasts_one_hour() -> None:
    entry = entry_from_csv_row(
        {"id": "4", "date": "2024-01-15", "time": "23:30", "text": "Демо проекта по хакатону"}
    )

    assert entry.type is EventType.MEETING
    assert entry.ends_at == entry.starts_at + timedelta(hours=1)
    assert entry.ends_at.isoformat() == "2024-01-16T00:30:00+03:00"


def test_seed_file_is_built_from_current_csv() -> None:
    assert render_history_file(read_csv_entries(CSV_FILE)) == SEED_FILE.read_text(
        encoding="utf-8"
    ), "app/seed/events_seed.json устарел — выполните `uv run python -m scripts.build_seed`"


def test_seed_file_has_all_csv_rows_without_reminders() -> None:
    entries = read_history_file()

    assert [entry.id for entry in entries] == list(range(1, CSV_ROWS + 1))
    assert Counter(entry.type for entry in entries) == {
        EventType.TASK: 725,
        EventType.MEETING: 275,
    }
    assert all(entry.has_time for entry in entries)
    assert all(entry.starts_at.utcoffset() == timedelta(hours=3) for entry in entries)


def test_seed_file_round_trip_keeps_one_record_per_line(tmp_path: Path) -> None:
    entries = read_history_file()[:3]
    seed_file = tmp_path / "seed.json"
    seed_file.write_text(render_history_file(entries), encoding="utf-8")

    assert read_history_file(seed_file) == entries
    assert len(seed_file.read_text(encoding="utf-8").splitlines()) == len(entries) + 2
