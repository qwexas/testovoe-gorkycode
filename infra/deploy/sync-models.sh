#!/usr/bin/env bash
# Копирует на сервер только нужные веса из ./models (около 4,7 ГБ из 11 ГБ локального кэша):
# эмбеддинги USER-bge-m3, Whisper large-v3-turbo / medium / small (замер Q20), Silero.
# Каталог моделей Hugging Face здесь хранит файлы в общем ./models/blobs через
# относительные ссылки, поэтому копируются и сами каталоги моделей, и их блобы.
set -euo pipefail

HOST="${DEPLOY_HOST:-homeserver}"
REMOTE_DIR="${DEPLOY_DIR:-gorkycode}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
MODELS=(
  models--deepvk--USER-bge-m3
  models--mobiuslabsgmbh--faster-whisper-large-v3-turbo
  models--Systran--faster-whisper-medium
  models--Systran--faster-whisper-small
  silero
)

cd "$ROOT/models"
LIST="$(mktemp)"
trap 'rm -f "$LIST"' EXIT
{
  echo CACHEDIR.TAG
  for model in "${MODELS[@]}"; do
    find "$model" \( -type f -o -type l \)
    find "$model" -type l -exec realpath {} \; | sed "s|^$ROOT/models/||"
  done
} | sort -u > "$LIST"

rsync -az --files-from="$LIST" ./ "$HOST:$REMOTE_DIR/models/"
# Контейнер работает не от qwe: каталог должен быть доступен ему на запись (lock-файлы HF).
ssh "$HOST" "chmod -R a+rwX $REMOTE_DIR/models"
