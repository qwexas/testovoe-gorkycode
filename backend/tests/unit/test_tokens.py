"""Токены сессии и подписки на календарь."""

import hashlib

from app.core.tokens import hash_session_token, new_calendar_token, new_session_token


def test_session_tokens_are_random_and_long() -> None:
    tokens = {new_session_token() for _ in range(20)}

    assert len(tokens) == 20
    assert all(len(token) >= 43 for token in tokens)


def test_session_token_is_stored_as_sha256() -> None:
    token = new_session_token()

    digest = hash_session_token(token)

    assert digest == hashlib.sha256(token.encode()).hexdigest()
    assert token not in digest


def test_calendar_token_is_url_safe() -> None:
    token = new_calendar_token()

    assert len(token) >= 32
    assert all(char.isalnum() or char in "-_" for char in token)
