"""Определение IP клиента за Cloudflare и nginx."""

import pytest
from starlette.requests import Request

from app.api.dependencies import UNKNOWN_CLIENT, get_client_ip


def make_request(headers: dict[str, str], client: tuple[str, int] | None) -> Request:
    raw_headers = [(name.lower().encode(), value.encode()) for name, value in headers.items()]
    return Request({"type": "http", "headers": raw_headers, "client": client})


@pytest.mark.parametrize(
    ("headers", "client", "expected"),
    [
        ({"CF-Connecting-IP": "203.0.113.7", "X-Forwarded-For": "10.0.0.1"}, None, "203.0.113.7"),
        ({"X-Forwarded-For": " 198.51.100.4 , 10.0.0.1"}, ("127.0.0.1", 1), "198.51.100.4"),
        ({"CF-Connecting-IP": "  "}, ("192.0.2.9", 5000), "192.0.2.9"),
        ({}, ("192.0.2.9", 5000), "192.0.2.9"),
        ({}, None, UNKNOWN_CLIENT),
    ],
)
def test_client_ip_priority(
    headers: dict[str, str], client: tuple[str, int] | None, expected: str
) -> None:
    assert get_client_ip(make_request(headers, client)) == expected
