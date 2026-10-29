"""OpenAPI соответствует контракту и сохранённому `contracts/openapi.json`."""

import json
from typing import Any

import pytest

from app.export_openapi import OPENAPI_PATH, build_openapi_app, render_openapi

CONTRACT_OPERATIONS = {
    ("get", "/api/health"),
    ("get", "/api/me"),
    ("post", "/api/profiles"),
    ("post", "/api/profiles/restore"),
    ("delete", "/api/me"),
    ("post", "/api/chat"),
    ("post", "/api/voice"),
    ("get", "/api/dialog"),
    ("post", "/api/tts"),
    ("post", "/api/actions/{action_id}/undo"),
    ("get", "/api/events"),
    ("post", "/api/events"),
    ("patch", "/api/events/{id}"),
    ("delete", "/api/events/{id}"),
    ("get", "/api/calendar.ics"),
    ("get", "/api/calendar/{token}.ics"),
}

CONTRACT_SCHEMAS = {
    "Event",
    "EventCreate",
    "EventUpdate",
    "Profile",
    "ChatMessage",
    "AssistantReply",
    "Period",
    "Choice",
    "Pending",
    "Undo",
    "ErrorResponse",
}


@pytest.fixture(scope="module")
def openapi() -> dict[str, Any]:
    schema: dict[str, Any] = json.loads(render_openapi(build_openapi_app()))
    return schema


def test_saved_contract_is_up_to_date() -> None:
    saved = OPENAPI_PATH.read_text(encoding="utf-8")

    assert saved == render_openapi(build_openapi_app()), (
        "contracts/openapi.json устарел — выполните `make contract`"
    )


def test_all_contract_endpoints_are_declared(openapi: dict[str, Any]) -> None:
    declared = {(method, path) for path, item in openapi["paths"].items() for method in item}

    assert declared == CONTRACT_OPERATIONS


def test_contract_models_are_published(openapi: dict[str, Any]) -> None:
    published = set(openapi["components"]["schemas"])

    assert CONTRACT_SCHEMAS - published == set()


def test_errors_use_single_format_everywhere(openapi: dict[str, Any]) -> None:
    assert "HTTPValidationError" not in openapi["components"]["schemas"]
    for item in openapi["paths"].values():
        for operation in item.values():
            for status, response in operation["responses"].items():
                if status.startswith(("4", "5")):
                    schema = response["content"]["application/json"]["schema"]
                    assert schema == {"$ref": "#/components/schemas/ErrorResponse"}


def test_period_uses_from_key(openapi: dict[str, Any]) -> None:
    period = openapi["components"]["schemas"]["Period"]

    assert set(period["required"]) == {"from", "to", "label"}


def test_session_security_and_explicit_creation_are_documented(openapi: dict[str, Any]) -> None:
    paths = openapi["paths"]
    assert paths["/api/profiles"]["post"]["security"] == [{"ProfileCreation": []}]
    assert "403" in paths["/api/profiles"]["post"]["responses"]
    assert "security" not in paths["/api/profiles/restore"]["post"]
    assert "security" not in paths["/api/health"]["get"]
    assert "security" not in paths["/api/calendar/{token}.ics"]["get"]
    for item in paths.values():
        for operation in item.values():
            if {"ProfileSession": []} in operation.get("security", []):
                assert "401" in operation["responses"]
