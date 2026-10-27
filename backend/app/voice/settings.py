"""Настройки распознавания (`STT_*`) и синтеза речи (`TTS_*`) из окружения и корневого `.env`."""

from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.config import ENV_FILE

DEFAULT_WHISPER_MODEL = "large-v3-turbo"
"""Q20 и замер `docs/voice.md`: точнее medium и small; medium быстрее лишь на ~20 %."""
DEFAULT_BEAM_SIZE = 5
"""Луч 1 быстрее всего на ~0,1 с на фразу и на 1 п. п. менее точен."""
DEFAULT_STT_CPU_THREADS = 8
SILERO_VOICES = ("xenia", "baya", "aidar")
"""Голоса Silero v4_ru, из которых выбирают на слух (Q38)."""
DEFAULT_VOICE = "baya"
"""Выбран владельцем на слух 27.10 (Q38)."""

SileroSampleRate = Literal[8000, 24000, 48000]
"""Частоты, которые умеет Silero v4_ru."""


class SpeechToTextSettings(BaseSettings):
    """Распознавание речи faster-whisper на CPU (Q5, Q20).

    `cache_dir` — каталог весов: локально `./models` репозитория (он в `.gitignore`),
    в Docker — пусто, тогда веса лежат в `HF_HOME` (том `/models`).
    """

    model_config = SettingsConfigDict(
        env_prefix="STT_", env_file=ENV_FILE, env_file_encoding="utf-8", extra="ignore"
    )

    model: str = Field(
        default=DEFAULT_WHISPER_MODEL,
        description="Модель faster-whisper: `large-v3-turbo`, `medium`, `small` или путь к CT2",
    )
    cache_dir: Path | None = Field(
        default=None, description="Каталог весов; пусто — кэш Hugging Face (`HF_HOME`)"
    )
    cpu_threads: int = Field(
        default=DEFAULT_STT_CPU_THREADS,
        ge=0,
        description="Потоков CTranslate2 на одно распознавание; 0 — по умолчанию библиотеки (4)",
    )
    max_concurrency: int = Field(
        default=1,
        ge=1,
        description="Сколько фраз распознаётся одновременно; остальные ждут в очереди",
    )
    beam_size: int = Field(default=DEFAULT_BEAM_SIZE, ge=1, description="Ширина луча декодера")
    domain_prompt: bool = Field(
        default=True,
        description="Подсказывать декодеру имя ассистента и лексику задач и встреч",
    )
    warm_up_on_startup: bool = Field(
        default=True, description="Грузить модель при старте, а не на первой фразе"
    )


class TextToSpeechSettings(BaseSettings):
    """Синтез речи Silero v4_ru на CPU (Q13).

    `cache_dir` — куда скачать файл модели; пусто — каталог torch hub (`TORCH_HOME`).
    """

    model_config = SettingsConfigDict(
        env_prefix="TTS_", env_file=ENV_FILE, env_file_encoding="utf-8", extra="ignore"
    )

    voice: str = Field(default=DEFAULT_VOICE, description="Голос по умолчанию: baya, xenia, aidar")
    cache_dir: Path | None = Field(
        default=None, description="Каталог файла модели; пусто — `TORCH_HOME/hub/silero`"
    )
    sample_rate: SileroSampleRate = Field(default=48000, description="Частота синтеза, Гц")
    warm_up_on_startup: bool = Field(
        default=True, description="Грузить модель при старте, а не на первой озвучке"
    )

    @field_validator("voice")
    @classmethod
    def _known_voice(cls, voice: str) -> str:
        if voice not in SILERO_VOICES:
            raise ValueError(f"голос должен быть одним из: {', '.join(SILERO_VOICES)}")
        return voice
