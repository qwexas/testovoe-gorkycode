"""Приём записи для `/api/voice`: формат, предел размера при потоковом чтении, поле формы."""

import itertools
from collections.abc import Iterator

import httpx
import pytest
from fastapi.exceptions import RequestValidationError
from starlette.requests import Request
from starlette.types import Message

from app.api.audio_upload import MAX_BODY_BYTES, read_audio_upload
from app.core.errors import AudioTooLargeError, AudioUnsupportedError
from app.voice.interfaces import MAX_AUDIO_BYTES

CHUNK_BYTES = 64 * 1024
SPEECH = b"OggS\x00fake-opus-frames"


class StreamedRequest:
    """Тело запроса, которое приходит по частям; считает, сколько частей прочитано."""

    def __init__(self, chunks: Iterator[bytes], headers: dict[str, str]) -> None:
        self._chunks = chunks
        self.headers = headers
        self.chunks_read = 0

    def build(self) -> Request:
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/api/voice",
            "headers": [(name.encode(), value.encode()) for name, value in self.headers.items()],
        }
        return Request(scope, self._receive)

    async def _receive(self) -> Message:
        chunk = next(self._chunks, None)
        if chunk is None:
            return {"type": "http.request", "body": b"", "more_body": False}
        self.chunks_read += 1
        return {"type": "http.request", "body": chunk, "more_body": True}


def form(
    data: bytes, content_type: str = "audio/webm", field: str = "audio"
) -> tuple[bytes, dict[str, str]]:
    """Тело `multipart/form-data` с одной записью и его заголовки."""
    encoded = httpx.Request("POST", "http://test", files={field: ("voice", data, content_type)})
    return encoded.read(), {"content-type": encoded.headers["content-type"]}


def streamed(body: bytes, headers: dict[str, str]) -> StreamedRequest:
    chunks = (body[start : start + CHUNK_BYTES] for start in range(0, len(body), CHUNK_BYTES))
    return StreamedRequest(chunks, headers)


async def read(body: bytes, headers: dict[str, str]) -> tuple[bytes, str]:
    clip = await read_audio_upload(streamed(body, headers).build())
    return clip.data, clip.content_type


@pytest.mark.parametrize(
    ("declared", "expected"),
    [
        ("audio/webm;codecs=opus", "audio/webm"),
        ("audio/webm", "audio/webm"),
        ("audio/ogg; codecs=opus", "audio/ogg"),
        ("audio/mp4", "audio/mp4"),
        ("audio/aac", "audio/aac"),
        ("audio/x-m4a", "audio/x-m4a"),
        ("audio/wav", "audio/wav"),
        ("audio/x-wav", "audio/x-wav"),
        ("audio/mpeg", "audio/mpeg"),
        ("Audio/WebM;Codecs=opus", "audio/webm"),
    ],
)
async def test_supported_formats_pass_without_parameters(declared: str, expected: str) -> None:
    assert await read(*form(SPEECH, declared)) == (SPEECH, expected)


@pytest.mark.parametrize(
    "declared", ["application/octet-stream", "text/plain", "video/mp4", "image/png", ""]
)
async def test_unsupported_format_is_rejected(declared: str) -> None:
    with pytest.raises(AudioUnsupportedError) as raised:
        await read(*form(SPEECH, declared))

    assert raised.value.code == "audio_unsupported"


async def test_part_without_content_type_is_unsupported() -> None:
    boundary = "gorky"
    body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="audio"; filename="voice"\r\n\r\n'
        "data\r\n"
        f"--{boundary}--\r\n"
    ).encode()

    with pytest.raises(AudioUnsupportedError):
        await read(body, {"content-type": f"multipart/form-data; boundary={boundary}"})


async def test_record_of_exactly_ten_megabytes_is_accepted() -> None:
    data, _ = await read(*form(b"\x01" * MAX_AUDIO_BYTES))

    assert len(data) == MAX_AUDIO_BYTES


async def test_record_one_byte_over_limit_is_too_large() -> None:
    with pytest.raises(AudioTooLargeError) as raised:
        await read(*form(b"\x01" * (MAX_AUDIO_BYTES + 1)))

    assert raised.value.code == "audio_too_large"


async def test_reading_stops_at_limit_without_content_length() -> None:
    body, headers = form(b"\x01" * (2 * MAX_AUDIO_BYTES))
    request = streamed(body, headers)

    with pytest.raises(AudioTooLargeError):
        await read_audio_upload(request.build())

    assert request.chunks_read * CHUNK_BYTES <= MAX_BODY_BYTES + CHUNK_BYTES


async def test_endless_record_is_cut_off() -> None:
    boundary = "gorky"
    part_headers = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="audio"; filename="voice"\r\n'
        "Content-Type: audio/webm\r\n\r\n"
    ).encode()
    endless = itertools.chain([part_headers], itertools.repeat(b"\x01" * CHUNK_BYTES))
    request = StreamedRequest(
        endless, {"content-type": f"multipart/form-data; boundary={boundary}"}
    )

    with pytest.raises(AudioTooLargeError):
        await read_audio_upload(request.build())

    assert request.chunks_read * CHUNK_BYTES <= MAX_BODY_BYTES + CHUNK_BYTES


async def test_declared_oversize_is_rejected_before_reading() -> None:
    body, headers = form(SPEECH)
    request = streamed(body, headers | {"content-length": str(MAX_BODY_BYTES + 1)})

    with pytest.raises(AudioTooLargeError):
        await read_audio_upload(request.build())

    assert request.chunks_read == 0


async def test_unsupported_format_is_rejected_before_record_is_read() -> None:
    body, headers = form(b"\x01" * (4 * CHUNK_BYTES), "text/plain")
    request = streamed(body, headers)

    with pytest.raises(AudioUnsupportedError):
        await read_audio_upload(request.build())

    assert request.chunks_read == 1


async def test_other_fields_are_skipped() -> None:
    encoded = httpx.Request(
        "POST",
        "http://test",
        data={"note": "лишнее поле"},
        files={"audio": ("voice", SPEECH, "audio/ogg")},
    )
    headers = {"content-type": encoded.headers["content-type"]}

    assert await read(encoded.read(), headers) == (SPEECH, "audio/ogg")


@pytest.mark.parametrize(
    ("body", "headers"),
    [
        form(SPEECH, field="voice"),
        (b'{"audio": "x"}', {"content-type": "application/json"}),
        (b"", {"content-type": "multipart/form-data"}),
        (form(SPEECH)[0][:-10], form(SPEECH)[1]),
    ],
    ids=["other-field", "json", "no-boundary", "truncated"],
)
async def test_missing_audio_field_is_validation_error(
    body: bytes, headers: dict[str, str]
) -> None:
    with pytest.raises(RequestValidationError) as raised:
        await read(body, headers)

    assert raised.value.errors()[0]["loc"] == ("body", "audio")
