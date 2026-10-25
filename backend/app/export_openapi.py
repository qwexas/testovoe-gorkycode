"""Выгрузка OpenAPI в `contracts/openapi.json`: `uv run python -m app.export_openapi`.

Схема не зависит от окружения, поэтому приложение собирается с заглушечными
настройками — `.env` для выгрузки не нужен.
"""

import json
import sys
from pathlib import Path
from typing import Any

from fastapi import FastAPI

from app.config import REPOSITORY_ROOT, Settings
from app.factory import create_app

OPENAPI_PATH = REPOSITORY_ROOT / "contracts" / "openapi.json"

_EXPORT_SETTINGS: dict[str, Any] = {
    "database_url": "postgresql+asyncpg://openapi:openapi@127.0.0.1:1/openapi",
    "app_secret": "openapi-export-placeholder-secret-0000",
}


def build_openapi_app() -> FastAPI:
    """Приложение для выгрузки схемы, независимое от окружения."""
    return create_app(Settings(_env_file=None, **_EXPORT_SETTINGS))


def render_openapi(app: FastAPI) -> str:
    """OpenAPI в стабильном виде: отступ 2, ключи по алфавиту, перевод строки в конце."""
    return json.dumps(app.openapi(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def main() -> None:
    """Пишет схему в путь из аргумента или в `contracts/openapi.json`."""
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else OPENAPI_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_openapi(build_openapi_app()), encoding="utf-8")
    print(f"OpenAPI записан в {target}")


if __name__ == "__main__":
    main()
