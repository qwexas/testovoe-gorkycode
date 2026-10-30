"""случайные токены: сессия в cookie, ссылка подписки на календарь, id отменяемого действия."""

import hashlib
import secrets

SESSION_TOKEN_BYTES = 32
CALENDAR_TOKEN_BYTES = 24
ACTION_ID_BYTES = 16


def new_session_token() -> str:
    """случайный токен сессии для cookie; в базе хранится только его хэш."""
    return secrets.token_urlsafe(SESSION_TOKEN_BYTES)


def hash_session_token(token: str) -> str:
    """SHA-256 токена сессии (hex) — по нему профиль ищется в базе."""
    return hashlib.sha256(token.encode()).hexdigest()


def new_calendar_token() -> str:
    """секрет ссылки подписки `webcal://…/api/calendar/{token}.ics`."""
    return secrets.token_urlsafe(CALENDAR_TOKEN_BYTES)


def new_action_id() -> str:
    """идентификатор отменяемого действия для `POST /api/actions/{action_id}/undo`."""
    return secrets.token_urlsafe(ACTION_ID_BYTES)
