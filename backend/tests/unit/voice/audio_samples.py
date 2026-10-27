"""Короткие записи для тестов, собранные PyAV в памяти: без файлов и внешнего ffmpeg."""

import io
from dataclasses import dataclass, field

import av
import numpy as np
from numpy.typing import NDArray

TONE_HZ = 440
TONE_AMPLITUDE = 0.3


@dataclass(frozen=True, slots=True)
class AudioSpec:
    """Как закодировать тон: контейнер, кодек, длительность, частота, каналы."""

    container: str
    codec: str
    seconds: float = 1.0
    sample_rate: int = 48_000
    layout: str = "mono"
    options: dict[str, str] = field(default_factory=dict)


def tone(seconds: float, sample_rate: int) -> NDArray[np.float32]:
    """Синусоида 440 Гц."""
    moments = np.arange(int(seconds * sample_rate)) / sample_rate
    return (TONE_AMPLITUDE * np.sin(2 * np.pi * TONE_HZ * moments)).astype(np.float32)


def encoded(spec: AudioSpec) -> bytes:
    """Тон, закодированный по `spec`."""
    mono = (tone(spec.seconds, spec.sample_rate) * 32_767).astype(np.int16)
    channels = 2 if spec.layout == "stereo" else 1
    interleaved = np.repeat(mono, channels).reshape(1, -1)
    buffer = io.BytesIO()
    with av.open(buffer, mode="w", format=spec.container, options=spec.options) as container:
        stream = container.add_stream(spec.codec, rate=spec.sample_rate, layout=spec.layout)
        frame = av.AudioFrame.from_ndarray(interleaved, format="s16", layout=spec.layout)
        frame.sample_rate = spec.sample_rate
        for packet in [*stream.encode(frame), *stream.encode(None)]:
            container.mux(packet)
    return buffer.getvalue()


def video_only_mp4() -> bytes:
    """mp4 без звуковой дорожки: один кадр видео."""
    buffer = io.BytesIO()
    with av.open(buffer, mode="w", format="mp4") as container:
        stream = container.add_stream("mpeg4", rate=1)
        stream.width = 16
        stream.height = 16
        stream.pix_fmt = "yuv420p"
        frame = av.VideoFrame.from_ndarray(np.zeros((16, 16, 3), dtype=np.uint8), format="rgb24")
        for packet in [*stream.encode(frame), *stream.encode(None)]:
            container.mux(packet)
    return buffer.getvalue()
