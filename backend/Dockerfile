# Бэкенд «Горький»: FastAPI + uvicorn.
# Сборка из docker-compose: контекст ./backend и дополнительный контекст certs=./infra/certs.
# Вручную: docker build --build-context certs=infra/certs backend

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    VIRTUAL_ENV=/app/.venv \
    PATH="/app/.venv/bin:$PATH" \
    SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt \
    REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt \
    TZ=Europe/Moscow

COPY --from=ghcr.io/astral-sh/uv:0.12.6 /uv /usr/local/bin/uv

# ffmpeg — перекодирование голоса (Safari присылает mp4/aac); tzdata — Europe/Moscow.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates ffmpeg tzdata \
    && rm -rf /var/lib/apt/lists/*

# Корневой сертификат Минцифры для GigaChat: проверку TLS не отключаем, а доверяем ему.
COPY --from=certs russian_trusted_root_ca.pem /usr/local/share/ca-certificates/russian_trusted_root_ca.crt
RUN update-ca-certificates

WORKDIR /app

COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --locked --no-dev --no-install-project

COPY alembic.ini docker-entrypoint.sh ./
COPY migrations ./migrations
COPY app ./app

RUN useradd --system --no-create-home gorky \
    && chmod +x docker-entrypoint.sh
USER gorky

EXPOSE 8000
ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
