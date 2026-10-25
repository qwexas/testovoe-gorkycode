"""Собирает `app/seed/events_seed.json` из CSV истории (решение Q22).

Запуск из каталога `backend`: `uv run python -m scripts.build_seed`.
Файл результата коммитится: приложение читает его, а не CSV.
"""

import csv
from collections import Counter
from pathlib import Path

from app.config import REPOSITORY_ROOT
from app.core.history_source import (
    SEED_FILE,
    HistoryEntry,
    entry_from_csv_row,
    render_history_file,
)

CSV_FILE = REPOSITORY_ROOT / "GORKYCODE тестовое" / "voice_assistant_events_1000.csv"


def read_csv_entries(path: Path) -> list[HistoryEntry]:
    """Записи из CSV; `utf-8-sig` снимает BOM в начале файла."""
    with path.open(encoding="utf-8-sig", newline="") as csv_file:
        return [entry_from_csv_row(row) for row in csv.DictReader(csv_file)]


def main() -> None:
    """Перечитывает CSV, перезаписывает seed-файл и печатает число записей по типам."""
    entries = read_csv_entries(CSV_FILE)
    SEED_FILE.parent.mkdir(parents=True, exist_ok=True)
    SEED_FILE.write_text(render_history_file(entries), encoding="utf-8")
    types = Counter(entry.type.value for entry in entries)
    print(f"{SEED_FILE}: {len(entries)} записей, по типам: {dict(types)}")


if __name__ == "__main__":
    main()
