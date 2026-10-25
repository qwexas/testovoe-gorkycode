# «Горький» — команды разработки. Список: make help

SHELL := /bin/bash
.DEFAULT_GOAL := help

BACKEND_DIR := backend
FRONTEND_DIR := frontend
PNPM := $(shell command -v pnpm >/dev/null 2>&1 && echo pnpm || echo npx -y pnpm@12)
UV_RUN := cd $(BACKEND_DIR) && uv run

.PHONY: help install db migrate dev test test-backend lint lint-backend format \
    contract contract-backend up down

help: ## Показать команды
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  make %-18s %s\n", $$1, $$2}'

install: ## Установить зависимости бэкенда и фронта
	cd $(BACKEND_DIR) && uv sync
	$(PNPM) --dir $(FRONTEND_DIR) install

db: ## Поднять PostgreSQL (127.0.0.1:5433) и дождаться готовности
	docker compose up -d --wait db

migrate: ## Применить миграции к DATABASE_URL
	$(UV_RUN) alembic upgrade head

dev: db migrate ## API на :8100 и фронт на :3100 с перезагрузкой; Ctrl+C гасит оба
	@echo "API: http://127.0.0.1:8100/api/docs   UI: http://localhost:3100"
	@trap 'kill $$(jobs -p) 2>/dev/null' INT TERM EXIT; \
	( cd $(BACKEND_DIR) && uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8100 ) & \
	$(PNPM) --dir $(FRONTEND_DIR) dev & \
	wait

test: test-backend ## Тесты бэкенда и проверка типов фронта
	$(PNPM) --dir $(FRONTEND_DIR) typecheck

test-backend: ## Тесты бэкенда (интеграционные — при доступном DATABASE_URL_TEST)
	$(UV_RUN) pytest

lint: lint-backend ## Линтеры бэкенда и фронта
	$(PNPM) --dir $(FRONTEND_DIR) lint

lint-backend: ## ruff check + ruff format --check + mypy
	$(UV_RUN) ruff check .
	$(UV_RUN) ruff format --check .
	$(UV_RUN) mypy

format: ## Отформатировать код бэкенда и фронта
	$(UV_RUN) ruff check --fix .
	$(UV_RUN) ruff format .
	$(PNPM) --dir $(FRONTEND_DIR) format

contract: contract-backend ## OpenAPI → contracts/openapi.json → типы фронта
	$(PNPM) --dir $(FRONTEND_DIR) gen:api

contract-backend: ## Только выгрузить contracts/openapi.json
	$(UV_RUN) python -m app.export_openapi

seed: ## Пересобрать backend/app/seed/events_seed.json из CSV организаторов
	$(UV_RUN) python -m scripts.build_seed

up: ## Собрать и запустить весь docker-compose
	docker compose up -d --build

down: ## Остановить docker-compose
	docker compose down
