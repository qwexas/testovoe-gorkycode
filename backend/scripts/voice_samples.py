"""Образцы голосов Silero для выбора на слух (Q38): одна реплика ассистента каждым голосом.

Запуск из каталога backend/ (веса Silero — в ./models/silero репозитория):
    uv run python -m scripts.voice_samples                 # → voice-samples/<голос>.ogg
    uv run python -m scripts.voice_samples --out /tmp/samples
"""

import argparse
import asyncio
from pathlib import Path

from app.voice.settings import SILERO_VOICES, TextToSpeechSettings
from app.voice.silero import SileroTextToSpeech

REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLES_DIR = REPO_ROOT / "voice-samples"
SAMPLE_REPLY = (
    "Я Горький. Встреча «Встреча с командой» — завтра, 27 октября, в 15:00. Сегодня у вас 2 задачи."
)
"""Типичный ответ: имя ассистента, название в кавычках, дата, время и число."""


async def write_samples(out_dir: Path) -> list[Path]:
    """Озвучивает `SAMPLE_REPLY` каждым голосом в `out_dir/<голос>.ogg`."""
    tts = SileroTextToSpeech(
        TextToSpeechSettings(_env_file=None, cache_dir=REPO_ROOT / "models" / "silero")
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for voice in SILERO_VOICES:
        clip = await tts.synthesize(SAMPLE_REPLY, voice)
        path = out_dir / f"{voice}.ogg"
        path.write_bytes(clip.data)
        paths.append(path)
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(description="Образцы голосов Silero")
    parser.add_argument("--out", type=Path, default=SAMPLES_DIR)
    args = parser.parse_args()
    for path in asyncio.run(write_samples(args.out)):
        print(f"{path} — {path.stat().st_size // 1024} КБ")


if __name__ == "__main__":
    main()
