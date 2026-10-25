"""Секретные токены профиля: сессия в cookie и ссылка подписки на календарь."""

import hashlib
import secrets

SESSION_TOKEN_BYTES = 32
CALENDAR_TOKEN_BYTES = 24


def new_session_token() -> str:
    """Случайный токен сессии для cookie; в базе хранится только его хэш."""
    return secrets.token_urlsafe(SESSION_TOKEN_BYTES)


def hash_session_token(token: str) -> str:
    """SHA-256 токена сессии (hex) — по нему профиль ищется в базе."""
    return hashlib.sha256(token.encode()).hexdigest()


def new_calendar_token() -> str:
    """Секрет ссылки подписки `webcal://…/api/calendar/{token}.ics`."""
    return secrets.token_urlsafe(CALENDAR_TOKEN_BYTES)
