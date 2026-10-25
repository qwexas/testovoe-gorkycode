"""Cookie профиля: атрибуты и доставка в любой ответ, включая ошибки."""

import httpx
from fastapi import FastAPI, Request

from app.api.session_cookie import (
    SESSION_COOKIE_NAME,
    SessionCookieChange,
    issue_session_cookie,
    render_session_cookie,
    revoke_session_cookie,
)
from app.core.errors import FeatureNotImplementedError

ONE_YEAR_SECONDS = 365 * 24 * 60 * 60


def cookie_attributes(header: str) -> dict[str, str]:
    attributes: dict[str, str] = {}
    for part in header.split(";"):
        name, _, value = part.strip().partition("=")
        attributes[name.lower()] = value
    return attributes


def test_issued_cookie_is_http_only_lax_for_one_year() -> None:
    header = render_session_cookie(SessionCookieChange(token="abc"), secure=True)

    attributes = cookie_attributes(header)
    assert attributes[SESSION_COOKIE_NAME] == "abc"
    assert attributes["max-age"] == str(ONE_YEAR_SECONDS)
    assert attributes["path"] == "/"
    assert attributes["samesite"].lower() == "lax"
    assert "httponly" in attributes
    assert "secure" in attributes


def test_secure_flag_follows_settings() -> None:
    header = render_session_cookie(SessionCookieChange(token="abc"), secure=False)

    assert "secure" not in cookie_attributes(header)


def test_revoked_cookie_expires_immediately() -> None:
    attributes = cookie_attributes(render_session_cookie(SessionCookieChange(None), secure=True))

    assert attributes[SESSION_COOKIE_NAME] == '""'
    assert attributes["max-age"] == "0"
    assert "1970" in attributes["expires"]


async def test_cookie_is_set_even_when_request_fails(
    offline_app: FastAPI, offline_client: httpx.AsyncClient
) -> None:
    @offline_app.get("/issue-then-fail")
    async def issue_then_fail(request: Request) -> None:
        issue_session_cookie(request, "fresh-token")
        raise FeatureNotImplementedError()

    response = await offline_client.get("/issue-then-fail")

    assert response.status_code == 501
    assert cookie_attributes(response.headers["set-cookie"])[SESSION_COOKIE_NAME] == "fresh-token"


async def test_revoke_overrides_earlier_issue(
    offline_app: FastAPI, offline_client: httpx.AsyncClient
) -> None:
    @offline_app.get("/issue-then-revoke")
    async def issue_then_revoke(request: Request) -> None:
        issue_session_cookie(request, "fresh-token")
        revoke_session_cookie(request)

    response = await offline_client.get("/issue-then-revoke")

    assert response.headers.get_list("set-cookie") == [
        render_session_cookie(SessionCookieChange(None), secure=False)
    ]


async def test_no_cookie_without_instruction(offline_client: httpx.AsyncClient) -> None:
    response = await offline_client.get("/api/health")

    assert "set-cookie" not in response.headers
