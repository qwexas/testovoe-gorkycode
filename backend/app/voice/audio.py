"""декодирование записей и кодирование озвучки через PyAV — в памяти, без файлов (Q35).

PyAV несёт свои библиотеки FFmpeg, поэтому внешний `ffmpeg` и временные файлы не нужны.
"""

import io
import itertools
from collections.abc import Iterator

import av
import numpy as np
from av.audio.stream import AudioStream
from av.container import InputContainer
from numpy.typing import NDArray

from app.core.errors import AudioTooLargeError, AudioUnsupportedError
from app.voice.interfaces import MAX_AUDIO_BYTES, MAX_AUDIO_SECONDS

SPEECH_SAMPLE_RATE = 16_000
"""частота, на которой работают модели распознавания (GigaAM, Whisper)."""
DURATION_TOLERANCE_SECONDS = 1.0
"""запас к пределу длительности: запись ровно на 60 с после кодека бывает чуть длиннее."""
MAX_SPEECH_SAMPLES = int((MAX_AUDIO_SECONDS + DURATION_TOLERANCE_SECONDS) * SPEECH_SAMPLE_RATE)

ACCEPTED_CONTAINERS = frozenset({"matroska,webm", "ogg", "mov,mp4,m4a,3gp,3g2,mj2", "wav", "mp3"})
"""контейнеры из контракта (webm, ogg, mp4, wav) и mp3 — как их называет FFmpeg."""

INT16_SCALE = 32_768.0
OGG_CONTENT_TYPE = "audio/ogg"
OPUS_BIT_RATE = 32_000
"""достаточно для разборчивой речи в моно: 5 с озвучки — около 20 КБ."""


def decode_speech(data: bytes) -> NDArray[np.float32]:
    """моно 16 кГц в диапазоне [-1, 1] из записи webm/opus, ogg, mp4/aac, wav или mp3.

    Raises:
        AudioTooLargeError: Больше `MAX_AUDIO_BYTES` или длиннее `MAX_AUDIO_SECONDS`.
        AudioUnsupportedError: Формат не из списка, нет звуковой дорожки или данные битые.
    """
    if len(data) > MAX_AUDIO_BYTES:
        raise AudioTooLargeError()
    try:
        with av.open(io.BytesIO(data), mode="r") as container:
            pieces = list(_mono_pcm(container, _speech_stream(container)))
    except av.FFmpegError as error:
        raise AudioUnsupportedError() from error
    if not pieces:
        return np.zeros(0, dtype=np.float32)
    return np.concatenate(pieces).astype(np.float32) / INT16_SCALE


def _speech_stream(container: InputContainer) -> AudioStream:
    if container.format.name not in ACCEPTED_CONTAINERS or not container.streams.audio:
        raise AudioUnsupportedError()
    return container.streams.audio[0]


def _mono_pcm(container: InputContainer, stream: AudioStream) -> Iterator[NDArray[np.int16]]:
    """отрезки моно 16 кГц; прерывается, как только запись длиннее предела."""
    resampler = av.AudioResampler(format="s16", layout="mono", rate=SPEECH_SAMPLE_RATE)
    total_samples = 0
    for frame in itertools.chain(container.decode(stream), [None]):
        for resampled in resampler.resample(frame):
            samples = resampled.to_ndarray().reshape(-1).astype(np.int16, copy=False)
            total_samples += samples.size
            if total_samples > MAX_SPEECH_SAMPLES:
                raise AudioTooLargeError()
            yield samples


def encode_ogg_opus(samples: NDArray[np.float32], sample_rate: int) -> bytes:
    """OGG/Opus из моно-сигнала в диапазоне [-1, 1]."""
    pcm = (np.clip(samples, -1.0, 1.0) * (INT16_SCALE - 1)).astype(np.int16)
    buffer = io.BytesIO()
    with av.open(buffer, mode="w", format="ogg") as container:
        stream = container.add_stream("libopus", rate=sample_rate, layout="mono")
        stream.bit_rate = OPUS_BIT_RATE
        frame = av.AudioFrame.from_ndarray(pcm.reshape(1, -1), format="s16", layout="mono")
        frame.sample_rate = sample_rate
        for packet in [*stream.encode(frame), *stream.encode(None)]:
            container.mux(packet)
    return buffer.getvalue()
