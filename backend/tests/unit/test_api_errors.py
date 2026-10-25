"""Единый формат ошибок API."""

import httpx
import pytest
from fastapi import FastAPI

from app.api.errors import ERROR_STATUS
from app.core.errors import (
    DomainError,
    ErrorCode,
    InvalidRecoveryCodeError,
    TooManyAttemptsError,
)
from tests.helpers import assert_error


def test_every_error_code_has_http_status() -> None:
    assert set(ERROR_STATUS) == set(ErrorCode)


async def test_unknown_path_is_not_found(offline_client: httpx.AsyncClient) -> None:
    response = await offline_client.get("/api/nothing-here")

    assert_error(response, 404, ErrorCode.NOT_FOUND)


async def test_wrong_method_keeps_status_and_format(offline_client: httpx.AsyncClient) -> None:
    response = await offline_client.put("/api/health")

    assert_error(response, 405, ErrorCode.VALIDATION_ERROR)
    assert "GET" in response.headers["allow"]


@pytest.mark.parametrize(
    ("error", "status_code"),
    [
        (InvalidRecoveryCodeError(), 400),
        (TooManyAttemptsError(retry_after_seconds=90), 429),
        (DomainError(), 500),
    ],
)
async def test_domain_errors_map_to_contract_status(
    offline_app: FastAPI,
    offline_client: httpx.AsyncClient,
    error: DomainError,
    status_code: int,
) -> None:
    @offline_app.get("/raise")
    async def raise_error() -> None:
        raise error

    response = await offline_client.get("/raise")

    assert_error(response, status_code, error.code)
    assert response.json()["error"]["message"] == error.message


async def test_rate_limit_error_has_retry_after_and_minutes(
    offline_app: FastAPI, offline_client: httpx.AsyncClient
) -> None:
    @offline_app.get("/raise")
    async def raise_error() -> None:
        raise TooManyAttemptsError(retry_after_seconds=61)

    response = await offline_client.get("/raise")

    assert response.headers["retry-after"] == "61"
    assert "через 2 мин." in response.json()["error"]["message"]


async def test_unexpected_exception_becomes_internal_error(offline_app: FastAPI) -> None:
    @offline_app.get("/crash")
    async def crash() -> None:
        raise RuntimeError("boom")

    transport = httpx.ASGITransport(app=offline_app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/crash")

    assert_error(response, 500, ErrorCode.INTERNAL_ERROR)
    assert "boom" not in response.text
