#!/usr/bin/env bash
# Деплой «Горького» на сервер по SSH: rsync кода → сборка и перезапуск docker compose.
#
# Секреты (.env) и веса моделей (models/) на сервере этот скрипт не трогает:
# .env создаётся один раз по образцу infra/deploy/env.production.example,
# веса — infra/deploy/sync-models.sh или первым стартом.
set -euo pipefail

HOST="${DEPLOY_HOST:-homeserver}"
REMOTE_DIR="${DEPLOY_DIR:-gorkycode}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

echo "→ код на $HOST:~/$REMOTE_DIR"
rsync -az --delete --exclude-from="$ROOT/infra/deploy/rsync-exclude" "$ROOT/" "$HOST:$REMOTE_DIR/"

echo "→ сборка и запуск"
ssh "$HOST" "cd $REMOTE_DIR && test -f .env && docker compose up -d --build --remove-orphans && docker compose ps"
