"""Декодирование записей браузеров и кодирование озвучки — в памяти, с пределами контракта."""

import numpy as np
import pytest

from app.core.errors import AudioTooLargeError, AudioUnsupportedError
from app.voice.audio import (
    DURATION_TOLERANCE_SECONDS,
    SPEECH_SAMPLE_RATE,
    decode_speech,
    encode_ogg_opus,
)
from app.voice.interfaces import MAX_AUDIO_BYTES, MAX_AUDIO_SECONDS
from tests.unit.voice.audio_samples import AudioSpec, encoded, tone, video_only_mp4

DURATION_PRECISION_SECONDS = 0.1
"""Кодеки добавляют задержку и дополняют последний кадр."""
LOW_RATE = 8_000
"""Длинные wav для проверки предела — на низкой частоте, чтобы тест был быстрым."""

BROWSER_FORMATS = {
    "chrome-webm-opus": AudioSpec("webm", "libopus"),
    "firefox-ogg-opus": AudioSpec("ogg", "libopus"),
    "safari-mp4-aac": AudioSpec(
        "mp4", "aac", sample_rate=44_100, options={"movflags": "frag_keyframe+empty_moov"}
    ),
    "plain-mp4-aac": AudioSpec("mp4", "aac"),
    "wav-pcm": AudioSpec("wav", "pcm_s16le", sample_rate=16_000),
    "mp3": AudioSpec("mp3", "mp3", sample_rate=44_100),
    "stereo-webm": AudioSpec("webm", "libopus", layout="stereo"),
}


@pytest.mark.parametrize("spec", BROWSER_FORMATS.values(), ids=BROWSER_FORMATS.keys())
def test_browser_formats_decode_to_mono_16k(spec: AudioSpec) -> None:
    samples = decode_speech(encoded(spec))

    assert samples.dtype == np.float32
    assert samples.ndim == 1
    assert samples.size / SPEECH_SAMPLE_RATE == pytest.approx(
        spec.seconds, abs=DURATION_PRECISION_SECONDS
    )
    assert np.abs(samples).max() <= 1.0
    assert np.abs(samples).max() > 0.1


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"definitely not audio",
        b"\x89PNG\r\n\x1a\n" + bytes(100),
        b"RIFF" + bytes(50),
    ],
    ids=["empty", "text", "png", "broken-wav"],
)
def test_garbage_is_unsupported(data: bytes) -> None:
    with pytest.raises(AudioUnsupportedError):
        decode_speech(data)


def test_container_outside_contract_is_unsupported() -> None:
    with pytest.raises(AudioUnsupportedError):
        decode_speech(encoded(AudioSpec("flac", "flac")))


def test_recording_without_audio_track_is_unsupported() -> None:
    with pytest.raises(AudioUnsupportedError):
        decode_speech(video_only_mp4())


def test_bytes_over_limit_are_too_large() -> None:
    with pytest.raises(AudioTooLargeError):
        decode_speech(bytes(MAX_AUDIO_BYTES + 1))


def test_bytes_at_limit_are_checked_as_audio() -> None:
    with pytest.raises(AudioUnsupportedError):
        decode_speech(bytes(MAX_AUDIO_BYTES))


def test_minute_long_recording_is_accepted() -> None:
    spec = AudioSpec("wav", "pcm_s16le", seconds=MAX_AUDIO_SECONDS, sample_rate=LOW_RATE)

    samples = decode_speech(encoded(spec))

    assert samples.size == MAX_AUDIO_SECONDS * SPEECH_SAMPLE_RATE


def test_recording_longer_than_limit_is_too_large() -> None:
    seconds = MAX_AUDIO_SECONDS + DURATION_TOLERANCE_SECONDS + 0.5
    spec = AudioSpec("wav", "pcm_s16le", seconds=seconds, sample_rate=LOW_RATE)

    with pytest.raises(AudioTooLargeError):
        decode_speech(encoded(spec))


def test_long_opus_recording_is_too_large_although_file_is_small() -> None:
    data = encoded(AudioSpec("ogg", "libopus", seconds=MAX_AUDIO_SECONDS + 5, sample_rate=LOW_RATE))

    assert len(data) < MAX_AUDIO_BYTES
    with pytest.raises(AudioTooLargeError):
        decode_speech(data)


@pytest.mark.parametrize("sample_rate", [24_000, 48_000])
def test_ogg_opus_round_trip_keeps_duration(sample_rate: int) -> None:
    speech = tone(2.0, sample_rate)

    data = encode_ogg_opus(speech, sample_rate)

    assert data.startswith(b"OggS")
    assert decode_speech(data).size / SPEECH_SAMPLE_RATE == pytest.approx(
        2.0, abs=DURATION_PRECISION_SECONDS
    )


def test_encoding_clips_out_of_range_samples() -> None:
    loud = np.full(4_800, 3.0, dtype=np.float32)

    samples = decode_speech(encode_ogg_opus(loud, 48_000))

    assert np.abs(samples).max() <= 1.0


def test_two_second_reply_is_compact() -> None:
    data = encode_ogg_opus(tone(2.0, 48_000), 48_000)

    assert len(data) < 16 * 1024
