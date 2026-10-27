"""Приём голосовой записи из `multipart/form-data` потоком — без диска и без лишней памяти.

Starlette сохраняет загруженные файлы во временный файл и читает тело целиком,
поэтому `/api/voice` разбирает поток сам:
- формат проверяется по `Content-Type` части `audio` до чтения её данных (415);
- в памяти копится только поле `audio`; как только запись превышает
  `MAX_AUDIO_BYTES`, чтение прекращается (413). Тело заметно больше записи
  отклоняется по `Content-Length` сразу, а без него — по мере чтения;
- запись не попадает ни на диск, ни в лог (Q35).
"""

from typing import TYPE_CHECKING, Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from python_multipart.exceptions import FormParserError
from python_multipart.multipart import MultipartParser, parse_options_header
from starlette.datastructures import Headers

from app.core.errors import AudioTooLargeError, AudioUnsupportedError
from app.voice.interfaces import MAX_AUDIO_BYTES, AudioClip

if TYPE_CHECKING:
    from python_multipart.multipart import MultipartCallbacks

AUDIO_FIELD = "audio"
MULTIPART_OVERHEAD_BYTES = 64 * 1024
"""Запас на границы и заголовки частей формы сверх самой записи."""
MAX_BODY_BYTES = MAX_AUDIO_BYTES + MULTIPART_OVERHEAD_BYTES
MULTIPART_FORM = "multipart/form-data"

SUPPORTED_AUDIO_TYPES = frozenset(
    {
        "audio/webm",
        "audio/ogg",
        "audio/mp4",
        "audio/aac",
        "audio/x-m4a",
        "audio/wav",
        "audio/x-wav",
        "audio/wave",
        "audio/vnd.wave",
        "audio/mpeg",
        "audio/mp3",
    }
)
"""Форматы записи: Chrome и Firefox (webm/ogg с Opus), Safari (mp4/aac), файлы wav и mp3.
Параметры вроде `;codecs=opus` допустимы."""

VOICE_REQUEST_BODY: dict[str, Any] = {
    "required": True,
    "content": {
        "multipart/form-data": {
            "schema": {
                "type": "object",
                "required": [AUDIO_FIELD],
                "properties": {
                    AUDIO_FIELD: {
                        "type": "string",
                        "format": "binary",
                        "description": (
                            "Запись голоса. `Content-Type` части: audio/webm, audio/ogg, "
                            "audio/mp4, audio/aac, audio/wav или audio/mpeg (можно с "
                            "параметрами, например `audio/webm;codecs=opus`)."
                        ),
                    }
                },
            }
        }
    },
}
"""Описание тела `/api/voice` для OpenAPI: FastAPI тело не разбирает, разбирает этот модуль."""


async def read_audio_upload(request: Request) -> AudioClip:
    """Запись из поля `audio` формы запроса.

    Raises:
        AudioUnsupportedError: Формат записи не поддерживается.
        AudioTooLargeError: Запись больше `MAX_AUDIO_BYTES`.
        RequestValidationError: Тело — не форма или в ней нет поля `audio`.
    """
    _reject_declared_oversize(request.headers)
    collector = _AudioPartCollector()
    parser = MultipartParser(_boundary(request.headers), collector.callbacks())
    received = 0
    try:
        async for chunk in request.stream():
            received += len(chunk)
            if received > MAX_BODY_BYTES:
                raise AudioTooLargeError()
            parser.write(chunk)
        parser.finalize()
    except FormParserError as error:
        raise _missing_audio() from error
    return collector.clip()


class _AudioPartCollector:
    """Колбэки потокового парсера: копит данные первого поля `audio`, остальное пропускает."""

    def __init__(self) -> None:
        self._header_name = bytearray()
        self._header_value = bytearray()
        self._part_headers: dict[bytes, bytes] = {}
        self._reading_audio = False
        self._audio_type: str | None = None
        self._audio = bytearray()
        self._audio_complete = False

    def callbacks(self) -> "MultipartCallbacks":
        """Словарь колбэков для `MultipartParser`."""
        return {
            "on_part_begin": self._on_part_begin,
            "on_header_field": self._on_header_field,
            "on_header_value": self._on_header_value,
            "on_header_end": self._on_header_end,
            "on_headers_finished": self._on_headers_finished,
            "on_part_data": self._on_part_data,
            "on_part_end": self._on_part_end,
        }

    def clip(self) -> AudioClip:
        """Собранная запись.

        Raises:
            RequestValidationError: Поля `audio` не было или оно оборвалось.
        """
        if self._audio_type is None or not self._audio_complete:
            raise _missing_audio()
        return AudioClip(data=bytes(self._audio), content_type=self._audio_type)

    def _on_part_begin(self) -> None:
        self._part_headers = {}

    def _on_header_field(self, data: bytes, start: int, end: int) -> None:
        self._header_name += data[start:end]

    def _on_header_value(self, data: bytes, start: int, end: int) -> None:
        self._header_value += data[start:end]

    def _on_header_end(self) -> None:
        self._part_headers[bytes(self._header_name).lower()] = bytes(self._header_value)
        self._header_name.clear()
        self._header_value.clear()

    def _on_headers_finished(self) -> None:
        self._reading_audio = self._audio_type is None and self._is_audio_field()
        if self._reading_audio:
            self._audio_type = _supported_audio_type(self._part_headers.get(b"content-type"))

    def _on_part_data(self, data: bytes, start: int, end: int) -> None:
        if not self._reading_audio:
            return
        if len(self._audio) + end - start > MAX_AUDIO_BYTES:
            raise AudioTooLargeError()
        self._audio += data[start:end]

    def _on_part_end(self) -> None:
        if self._reading_audio:
            self._audio_complete = True
            self._reading_audio = False

    def _is_audio_field(self) -> bool:
        _, options = _parse_header(self._part_headers.get(b"content-disposition"))
        return options.get(b"name") == AUDIO_FIELD.encode()


def _supported_audio_type(header: bytes | None) -> str:
    """MIME-тип записи без параметров.

    Raises:
        AudioUnsupportedError: Тип не указан или не из `SUPPORTED_AUDIO_TYPES`.
    """
    audio_type, _ = _parse_header(header)
    if audio_type not in SUPPORTED_AUDIO_TYPES:
        raise AudioUnsupportedError()
    return audio_type


def _reject_declared_oversize(headers: Headers) -> None:
    declared = headers.get("content-length", "")
    if declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        raise AudioTooLargeError()


def _boundary(headers: Headers) -> bytes:
    media_type, options = _parse_header(headers.get("content-type"))
    boundary = options.get(b"boundary")
    if media_type != MULTIPART_FORM or not boundary:
        raise _missing_audio()
    return boundary


def _parse_header(value: str | bytes | None) -> tuple[str, dict[bytes, bytes]]:
    """Значение заголовка в нижнем регистре и его параметры (`boundary`, `name`…)."""
    value_type, options = parse_options_header(value)
    return value_type.decode("latin-1").strip().lower(), options


def _missing_audio() -> RequestValidationError:
    """Та же ошибка, что FastAPI отдаёт за пропущенное поле формы: 422 «Поле: «audio»»."""
    return RequestValidationError(
        [{"type": "missing", "loc": ("body", AUDIO_FIELD), "msg": "Field required"}]
    )
