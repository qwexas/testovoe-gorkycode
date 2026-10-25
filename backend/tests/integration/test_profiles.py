"""Анонимные профили: автосоздание, «Новый профиль», восстановление по коду, удаление."""

import re

import httpx
import pytest

from app.api.session_cookie import SESSION_COOKIE_MAX_AGE_SECONDS, SESSION_COOKIE_NAME
from app.core.errors import ErrorCode
from app.core.history_source import read_history_file
from app.core.profiles import PROFILE_CREATION_WINDOW_SECONDS, PROFILE_CREATIONS_PER_ADDRESS
from app.core.recovery import RESTORE_ATTEMPTS_LIMIT
from tests.conftest import TEST_PUBLIC_BASE_URL
from tests.helpers import assert_error

pytestmark = pytest.mark.integration

RECOVERY_CODE_FORMAT = re.compile(r"[а-я]+-[а-я]+-[а-я]+-[0-9]{4}")
WRONG_CODE = "сирень-лиса-кедр-0000"
COOKIE_DOMAIN = "testserver.local"
HISTORY_SIZE = len(read_history_file())


def session_cookie(client: httpx.AsyncClient) -> str | None:
    return client.cookies.get(SESSION_COOKIE_NAME)


def replace_session_cookie(client: httpx.AsyncClient, token: str) -> None:
    client.cookies.clear()
    client.cookies.set(SESSION_COOKIE_NAME, token, domain=COOKIE_DOMAIN)


async def restore(client: httpx.AsyncClient, code: str, ip: str = "203.0.113.10") -> httpx.Response:
    return await client.post(
        "/api/profiles/restore", json={"code": code}, headers={"CF-Connecting-IP": ip}
    )


class TestAutoCreatedProfile:
    async def test_first_request_creates_profile_and_sets_cookie(
        self, client: httpx.AsyncClient
    ) -> None:
        response = await client.get("/api/me")

        assert response.status_code == 200
        profile = response.json()
        assert RECOVERY_CODE_FORMAT.fullmatch(profile["recovery_code"])
        assert profile["timezone"] == "Europe/Moscow"
        assert profile["events_count"] == HISTORY_SIZE
        set_cookie = response.headers["set-cookie"]
        assert f"Max-Age={SESSION_COOKIE_MAX_AGE_SECONDS}" in set_cookie
        assert "HttpOnly" in set_cookie
        assert "SameSite=lax" in set_cookie
        assert session_cookie(client)

    async def test_subscription_url_uses_public_host(self, client: httpx.AsyncClient) -> None:
        profile = (await client.get("/api/me")).json()

        host = TEST_PUBLIC_BASE_URL.removeprefix("https://")
        assert re.fullmatch(
            rf"webcal://{re.escape(host)}/api/calendar/[A-Za-z0-9_-]{{32}}\.ics",
            profile["calendar_subscription_url"],
        )

    async def test_repeated_request_returns_same_profile_without_code(
        self, client: httpx.AsyncClient
    ) -> None:
        first = (await client.get("/api/me")).json()

        response = await client.get("/api/me")

        assert response.json()["id"] == first["id"]
        assert response.json()["recovery_code"] is None
        assert "set-cookie" not in response.headers

    async def test_broken_cookie_gets_new_profile(self, client: httpx.AsyncClient) -> None:
        replace_session_cookie(client, "forged-token")

        response = await client.get("/api/me")

        assert response.json()["recovery_code"] is not None
        assert session_cookie(client) != "forged-token"

    async def test_failing_endpoint_still_keeps_created_profile(
        self, client: httpx.AsyncClient
    ) -> None:
        response = await client.post("/api/chat", json={"text": "Что у меня сегодня?"})
        assert_error(response, 501, ErrorCode.NOT_IMPLEMENTED)
        created_by_chat = session_cookie(client)

        me = await client.get("/api/me")

        assert created_by_chat
        assert session_cookie(client) == created_by_chat
        assert me.json()["recovery_code"] is None


class TestNewProfile:
    async def test_switches_cookie_to_fresh_profile(self, client: httpx.AsyncClient) -> None:
        old = (await client.get("/api/me")).json()
        old_cookie = session_cookie(client)

        response = await client.post("/api/profiles")

        assert response.status_code == 201
        new = response.json()
        assert new["id"] != old["id"]
        assert RECOVERY_CODE_FORMAT.fullmatch(new["recovery_code"])
        assert new["recovery_code"] != old["recovery_code"]
        assert session_cookie(client) != old_cookie
        assert (await client.get("/api/me")).json()["id"] == new["id"]

    async def test_old_session_of_this_device_is_closed(self, client: httpx.AsyncClient) -> None:
        old = (await client.get("/api/me")).json()
        old_cookie = session_cookie(client)
        await client.post("/api/profiles")

        assert old_cookie
        replace_session_cookie(client, old_cookie)
        response = await client.get("/api/me")

        assert response.json()["id"] != old["id"]
        assert response.json()["recovery_code"] is not None


class TestRestore:
    async def test_valid_code_returns_profile_and_switches_cookie(
        self, client: httpx.AsyncClient
    ) -> None:
        original = (await client.get("/api/me")).json()
        await client.post("/api/profiles")

        response = await restore(client, original["recovery_code"])

        assert response.status_code == 200
        assert response.json()["id"] == original["id"]
        assert response.json()["recovery_code"] is None
        assert (await client.get("/api/me")).json()["id"] == original["id"]

    async def test_code_is_accepted_in_any_case_and_spacing(
        self, client: httpx.AsyncClient
    ) -> None:
        original = (await client.get("/api/me")).json()
        sloppy_code = "  " + original["recovery_code"].upper().replace("-", "   ") + " "

        response = await restore(client, sloppy_code)

        assert response.json()["id"] == original["id"]

    async def test_restore_on_second_device_keeps_first_device_signed_in(
        self, client: httpx.AsyncClient, other_device: httpx.AsyncClient
    ) -> None:
        original = (await client.get("/api/me")).json()

        response = await restore(other_device, original["recovery_code"])

        assert response.json()["id"] == original["id"]
        assert (await client.get("/api/me")).json()["id"] == original["id"]
        assert (await other_device.get("/api/me")).json()["id"] == original["id"]

    @pytest.mark.parametrize("code", [WRONG_CODE, "просто текст"])
    async def test_wrong_code_is_rejected(self, client: httpx.AsyncClient, code: str) -> None:
        await client.get("/api/me")
        cookie_before = session_cookie(client)

        response = await restore(client, code)

        assert_error(response, 400, ErrorCode.INVALID_RECOVERY_CODE)
        assert session_cookie(client) == cookie_before

    async def test_empty_code_is_validation_error(self, client: httpx.AsyncClient) -> None:
        response = await restore(client, "   ")

        assert_error(response, 422, ErrorCode.VALIDATION_ERROR)

    async def test_attempts_are_limited_per_ip(
        self, client: httpx.AsyncClient, other_device: httpx.AsyncClient
    ) -> None:
        original = (await client.get("/api/me")).json()
        for _ in range(RESTORE_ATTEMPTS_LIMIT):
            assert (await restore(other_device, WRONG_CODE, ip="198.51.100.1")).status_code == 400

        blocked = await restore(other_device, original["recovery_code"], ip="198.51.100.1")

        assert_error(blocked, 429, ErrorCode.RATE_LIMITED)
        assert int(blocked.headers["retry-after"]) > 0
        allowed = await restore(other_device, original["recovery_code"], ip="198.51.100.2")
        assert allowed.json()["id"] == original["id"]


class TestDeleteMe:
    async def test_deletes_profile_and_clears_cookie(self, client: httpx.AsyncClient) -> None:
        profile = (await client.get("/api/me")).json()

        response = await client.delete("/api/me")

        assert response.status_code == 204
        assert "Max-Age=0" in response.headers["set-cookie"]
        assert session_cookie(client) is None
        assert_error(
            await restore(client, profile["recovery_code"]), 400, ErrorCode.INVALID_RECOVERY_CODE
        )

    async def test_other_devices_lose_access(
        self, client: httpx.AsyncClient, other_device: httpx.AsyncClient
    ) -> None:
        profile = (await client.get("/api/me")).json()
        await restore(other_device, profile["recovery_code"])

        await client.delete("/api/me")

        assert (await other_device.get("/api/me")).json()["id"] != profile["id"]

    async def test_without_profile_is_harmless(self, client: httpx.AsyncClient) -> None:
        response = await client.delete("/api/me")

        assert response.status_code == 204


class TestCreationLimit:
    """Не больше 20 новых профилей в час с одного IP — и «Новый профиль», и автосоздание."""

    async def exhaust_limit(self, client: httpx.AsyncClient, ip: str) -> None:
        for _ in range(PROFILE_CREATIONS_PER_ADDRESS):
            response = await client.post("/api/profiles", headers={"CF-Connecting-IP": ip})
            assert response.status_code == 201

    async def test_new_profile_over_limit_is_rate_limited(self, client: httpx.AsyncClient) -> None:
        await self.exhaust_limit(client, "198.51.100.7")
        cookie_before = session_cookie(client)

        response = await client.post("/api/profiles", headers={"CF-Connecting-IP": "198.51.100.7"})

        assert_error(response, 429, ErrorCode.RATE_LIMITED)
        assert "профилей" in response.json()["error"]["message"]
        assert 0 < int(response.headers["retry-after"]) <= PROFILE_CREATION_WINDOW_SECONDS
        assert session_cookie(client) == cookie_before
        assert (await client.get("/api/me")).status_code == 200

    async def test_auto_creation_shares_limit_and_address_is_per_ip(
        self, client: httpx.AsyncClient, other_device: httpx.AsyncClient
    ) -> None:
        await self.exhaust_limit(client, "198.51.100.8")

        blocked = await other_device.get(
            "/api/events", headers={"X-Forwarded-For": "198.51.100.8, 10.0.0.1"}
        )
        allowed = await other_device.get("/api/me", headers={"CF-Connecting-IP": "198.51.100.9"})

        assert_error(blocked, 429, ErrorCode.RATE_LIMITED)
        assert "set-cookie" not in blocked.headers
        assert allowed.status_code == 200
        assert allowed.json()["recovery_code"] is not None
